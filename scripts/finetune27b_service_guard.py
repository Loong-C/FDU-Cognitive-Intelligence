"""Remote service lifecycle guard. Snapshot is private and never logged.

The user authorized pausing for parallel draft generation and independent seed runs.
The exact target PID must be supplied; unrelated processes are never selected/killed.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import urllib.request


def proc_start(pid):
    text = Path(f'/proc/{pid}/stat').read_text()
    return text.rsplit(')', 1)[1].split()[19]


def capture(pid):
    p = Path('/proc')/str(pid)
    args = [s.decode() for s in (p/'cmdline').read_bytes().split(b'\0') if s]
    env = dict(s.decode().split('=', 1) for s in (p/'environ').read_bytes().split(b'\0') if s)
    if not any('vllm' in s.lower() for s in args) or not any('27b' in s.lower() for s in args):
        raise ValueError('PID is not the named 27B vLLM service')
    if not Path(f'/proc/{pid}').exists():
        raise ValueError('Service exited during capture')
    return {'pid': pid, 'start_time': proc_start(pid), 'argv': args,
            'environment': env, 'cwd': str((p/'cwd').resolve())}


def matching(snapshot):
    try:
        stat = Path(f"/proc/{snapshot['pid']}/stat").read_text().rsplit(')', 1)[1].split()
        return stat[0] != 'Z' and stat[19] == snapshot['start_time']
    except FileNotFoundError:
        return False


def health(base_url, key_file):
    key = key_file.read_text(encoding='utf-8-sig').strip()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    headers = {'Authorization': 'Bearer '+key, 'Content-Type': 'application/json'}
    request = urllib.request.Request(base_url.rstrip('/')+'/models', headers=headers)
    with opener.open(request, timeout=30) as response:
        ids = {m['id'] for m in json.load(response)['data']}
    if 'qwen38-27b' not in ids:
        raise ValueError('Restored endpoint has wrong model')
    payload = {'model': 'qwen38-27b', 'messages': [{'role':'user','content':'Reply with exactly QWEN_CONNECTION_OK'}],
               'temperature': 0, 'max_tokens': 64, 'chat_template_kwargs': {'enable_thinking':False}}
    request = urllib.request.Request(base_url.rstrip('/')+'/chat/completions', headers=headers,
                                     data=json.dumps(payload).encode())
    with opener.open(request, timeout=120) as response:
        answer = json.load(response)
    if answer['choices'][0]['message']['content'].strip() != 'QWEN_CONNECTION_OK':
        raise ValueError('Restored endpoint failed short generation')


def _restore(snapshot, directory, base_url, key_file):
    previous = directory/'restored_process.json'
    restored = json.loads(previous.read_text()) if previous.exists() else None
    if not matching(snapshot) and not (restored and matching(restored)):
        with (directory/'restored_service.log').open('ab') as log:
            service = subprocess.Popen(snapshot['argv'], cwd=snapshot['cwd'], env=snapshot['environment'],
                                       stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        previous.write_text(json.dumps({'pid': service.pid, 'start_time': proc_start(service.pid)}))
    last_error = None
    for _ in range(120):
        try:
            health(base_url, key_file)
            (directory/'restored.json').write_text(json.dumps({'restored': True, 'generation_checked': True}))
            current = snapshot if matching(snapshot) else json.loads(previous.read_text())
            pointer = directory.parent/'current_service.tmp'
            pointer.write_text(json.dumps({'pid':current['pid'],'start_time':current['start_time'],
                                           'recovery_directory':str(directory)}))
            pointer.replace(directory.parent/'current_service.json')
            return
        except Exception as error:
            last_error = type(error).__name__
            time.sleep(5)
    raise RuntimeError('Service restore health checks failed: '+str(last_error))


def restore(snapshot, directory, base_url, key_file):
    import fcntl
    with (directory/'restore.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        _restore(snapshot, directory, base_url, key_file)


def command_members(child, proc=Path('/proc')):
    """A session can retain NPU workers after its supervisor has already exited."""
    leader = proc/str(child['pid'])/'stat'
    if leader.exists():
        try:
            if leader.read_text().rsplit(')', 1)[1].split()[19] != child['start_time']:
                raise RuntimeError('Command leader PID was reused; refusing to signal its group')
        except FileNotFoundError:
            pass
    members = []
    for path in proc.glob('[0-9]*/stat'):
        try:
            fields = path.read_text().rsplit(')', 1)[1].split()
        except FileNotFoundError:
            continue
        if fields[0] != 'Z' and int(fields[2]) == child['pid'] and int(fields[3]) == child['pid']:
            if int(fields[19]) < int(child['start_time']):
                raise RuntimeError('Unexpected older process in command session')
            members.append(int(path.parent.name))
    return members


def stop_command(directory):
    path = directory/'command_process.json'
    if path.exists():
        child = json.loads(path.read_text())
        if command_members(child):
            try:
                os.killpg(child['pid'], signal.SIGTERM)
            except ProcessLookupError:
                return
            for _ in range(30):
                if not command_members(child):
                    return
                time.sleep(1)
            if command_members(child):
                try:
                    os.killpg(child['pid'], signal.SIGKILL)
                except ProcessLookupError:
                    pass
                for _ in range(10):
                    if not command_members(child):
                        return
                    time.sleep(1)


def watchdog(directory, base_url, key_file):
    parent = json.loads((directory/'guard_process.json').read_text())
    while matching(parent):
        if (directory/'restored.json').exists():
            return
        time.sleep(5)
    if not (directory/'restored.json').exists():
        try:
            stop_command(directory)
        finally:
            restore(json.loads((directory/'snapshot.private.json').read_text()), directory, base_url, key_file)


def guarded_run(snapshot, directory, command, base_url, key_file):
    # Snapshot/keys stay on the server with owner-only permissions.
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    snapshot_path = directory/'snapshot.private.json'
    descriptor = os.open(snapshot_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, 'w') as f:
        json.dump(snapshot, f)
    health(base_url, key_file)
    (directory/'guard_process.json').write_text(json.dumps({'pid': os.getpid(), 'start_time': proc_start(os.getpid())}))
    with (directory/'watchdog.log').open('ab') as log:
        subprocess.Popen([os.sys.executable, str(Path(__file__).resolve()), 'watchdog',
            '--directory', str(directory), '--base-url', base_url, '--key-file', str(key_file)],
            stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    def interrupted(signum, frame):
        raise KeyboardInterrupt('Guard interrupted')
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    try:
        if not matching(snapshot):
            raise RuntimeError('Target PID changed before stop')
        os.kill(snapshot['pid'], signal.SIGTERM)
        for _ in range(60):
            if not matching(snapshot):
                break
            time.sleep(1)
        if matching(snapshot):
            raise RuntimeError('Service did not stop gracefully; refusing broad kill')
        child = subprocess.Popen(command, start_new_session=True)
        (directory/'command_process.json').write_text(json.dumps({'pid': child.pid, 'start_time': proc_start(child.pid)}))
        code = child.wait()
        (directory/'command_exit.json').write_text(json.dumps({'returncode':code}))
        return code
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        try:
            stop_command(directory)
        finally:
            restore(snapshot, directory, base_url, key_file)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('action', choices=['inspect', 'pause-and-run', 'restore', 'watchdog'])
    p.add_argument('--pid', type=int)
    p.add_argument('--directory', type=Path, required=True)
    p.add_argument('--base-url', default='http://10.176.30.103:20027/v1')
    p.add_argument('--key-file', type=Path)
    a, command = p.parse_known_args()
    if a.action == 'inspect':
        s = capture(a.pid)
        print(json.dumps({'pid':s['pid'],'start_time':s['start_time'],'service_matches':True}))
        return
    if not a.key_file:
        p.error('--key-file required for health checks')
    if a.action == 'restore':
        restore(json.loads((a.directory/'snapshot.private.json').read_text()), a.directory, a.base_url, a.key_file)
    elif a.action == 'watchdog':
        watchdog(a.directory, a.base_url, a.key_file)
    else:
        command = command[1:] if command[:1] == ['--'] else command
        if not command:
            p.error('A training command is required')
        raise SystemExit(guarded_run(capture(a.pid), a.directory, command, a.base_url, a.key_file))


if __name__ == '__main__':
    main()
