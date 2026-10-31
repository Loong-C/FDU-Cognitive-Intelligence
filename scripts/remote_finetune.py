"""SSH transport for the isolated experiment; credentials are never logged."""
import argparse
import os
from pathlib import Path
import shlex
import sys


def main():
    import paramiko
    parser = argparse.ArgumentParser()
    parser.add_argument('--credentials', default=os.environ.get(
        'AB_SSH_ENV_FILE', 'F:/Personal/Code/A_B/.env.ssh.local'))
    sub = parser.add_subparsers(dest='action', required=True)
    cmd = sub.add_parser('exec')
    cmd.add_argument('command')
    cmd.add_argument('--timeout', type=int, default=60)
    script = sub.add_parser('python')
    script.add_argument('file', type=Path)
    script.add_argument('--interpreter', default='/root/ascend/bin/python')
    script.add_argument('--timeout', type=int, default=60)
    for name in ['upload', 'download']:
        p = sub.add_parser(name)
        p.add_argument('source')
        p.add_argument('destination')
    args = parser.parse_args()
    settings = dict(line.split('=', 1) for line in Path(args.credentials).read_text(
        encoding='utf-8-sig').splitlines() if line.strip() and not line.startswith('#'))
    client = paramiko.SSHClient()
    client.load_host_keys(str(Path(__file__).resolve().parents[1] / 'configs/server_ssh_known_hosts'))
    try:
        client.connect(settings['AB_SSH_HOST'], port=int(settings['AB_SSH_PORT']),
                       username=settings['AB_SSH_USER'], password=settings['AB_SSH_PASSWORD'],
                       timeout=15, banner_timeout=15, auth_timeout=15,
                       look_for_keys=False, allow_agent=False)
        if args.action in ('upload', 'download'):
            with client.open_sftp() as sftp:
                if args.action == 'upload':
                    sftp.put(args.source, args.destination)
                else:
                    Path(args.destination).parent.mkdir(parents=True, exist_ok=True)
                    sftp.get(args.source, args.destination)
            print('Transfer complete.')
            return
        command = args.command if args.action == 'exec' else (
            shlex.quote(args.interpreter) + ' -c ' + shlex.quote(args.file.read_text(encoding='utf-8')))
        stdin, stdout, stderr = client.exec_command(command, timeout=args.timeout)
        stdin.close()
        # Combine streams to prevent either SSH channel window from filling.
        stdout.channel.set_combine_stderr(True)
        for line in stdout:
            sys.stdout.write(line.replace(settings['AB_SSH_PASSWORD'], '[REDACTED]'))
            sys.stdout.flush()
        raise SystemExit(stdout.channel.recv_exit_status())
    finally:
        client.close()


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    main()
