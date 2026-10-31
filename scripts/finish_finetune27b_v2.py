"""Local completion watcher: collect and independently audit finished remote work.

This process checks remote results and adds an independent selection audit.
Training, service lifecycle and evaluation remain controlled by the existing
remote supervisor. Runtime state is ignored.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'outputs/finetune27b_v2'


class WatcherAlreadyRunning(RuntimeError):
    pass


@contextmanager
def single_watcher():
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT/'completion_watcher.lock').open('a+b') as lock:
        lock.seek(0,2)
        if lock.tell() == 0:
            lock.write(b'0'); lock.flush()
        lock.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError as error:
            raise WatcherAlreadyRunning('A completion watcher already holds the lock') from error
        try:
            yield
        finally:
            lock.seek(0)
            if os.name == 'nt':
                msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)
            else:
                fcntl.flock(lock.fileno(),fcntl.LOCK_UN)


def save_status(phase, **extra):
    value={'phase':phase,'utc':datetime.now(timezone.utc).isoformat(), 'pid':os.getpid(), **extra}
    temp=OUT/'completion_status.tmp'
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    temp.replace(OUT/'completion_status.json')
    print(json.dumps(value,ensure_ascii=False),flush=True)


def run(script, *arguments):
    result=subprocess.run([sys.executable,'-W','ignore',str(ROOT/'scripts'/script),*map(str,arguments)],
                          cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=90)
    if result.returncode:
        # The SSH helper redacts the credential; retain diagnostics in ignored log.
        raise RuntimeError(result.stderr[-2000:] or result.stdout[-2000:])
    return result.stdout


def main(once=False):
    with single_watcher():
        final=OUT/'completed/LOCAL_COMPLETION.json'
        if final.exists():
            save_status('already_completed',receipt=str(final))
            return
        while True:
            try:
                state=json.loads(run('remote_finetune.py','python',ROOT/'scripts/status_finetune27b_v2.py'))
            except (RuntimeError,subprocess.TimeoutExpired) as error:
                save_status('connection_retry',error=str(error))
                if once:
                    return
                time.sleep(60)
                continue
            save_status('remote_running',remote=state)
            if state.get('final_audit_passed') and state.get('formal_service_restored'):
                break
            if state.get('formal') and state.get('controller_running') is False:
                save_status('requires_attention',remote=state,
                            reason='Remote controller stopped before the complete audited result')
                return
            if once:
                return
            time.sleep(60)
        save_status('checking_selection')
        selection=json.loads(run('remote_finetune.py','python',ROOT/'scripts/check_finetune27b_selection.py'))
        if not selection.get('passed'):
            raise ValueError('Independent validation selection audit did not pass')
        save_status('collecting')
        subprocess.run([sys.executable,'-W','ignore',str(ROOT/'scripts/collect_finetune27b_v2.py'),'--publish'],
                       cwd=ROOT,check=True)
        directory=OUT/'completed/formal'
        server_audit=json.loads((directory/'audit.json').read_text(encoding='utf-8'))
        save_status('local_independent_audit')
        subprocess.run([sys.executable,str(ROOT/'scripts/recompute_finetune27b_v2.py'),str(directory)],
                       cwd=ROOT,check=True)
        independent=directory.parent/'local_audit'
        local_audit=json.loads((independent/'audit.json').read_text(encoding='utf-8'))
        if local_audit != server_audit or not local_audit['passed']:
            raise ValueError('Local independent audit differs from server audit')
        public=ROOT/'experiments/016_finetune_27b/revision_2/results'
        shutil.copyfile(independent/'audit.json',public/'local_audit.json')
        shutil.copyfile(independent/'recompute.json',public/'local_recompute.json')
        shutil.copyfile(directory/'selection_integrity.json',public/'selection_integrity.json')
        receipt={'completed':True,'utc':datetime.now(timezone.utc).isoformat(),
                 'local_independent_audit_passed':True,'results_sha256':local_audit['results_sha256'],
                 'selected_adapters':3,'report':str(public/'RESULTS.md'),
                 'service_recovery':json.loads((public/'service_recovery.json').read_text())}
        final.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        shutil.copyfile(final,public/'completion.json')
        save_status('completed',receipt=str(final))


if __name__ == '__main__':
    if hasattr(sys.stdout,'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--once',action='store_true',help='Check once; finish collection when ready')
    args=parser.parse_args()
    try:
        main(once=args.once)
    except WatcherAlreadyRunning:
        # A second launcher must not overwrite the active watcher's status file.
        print(json.dumps({'phase':'watcher_already_running','status_file':str(OUT/'completion_status.json')}))
    except Exception as error:
        save_status('requires_attention',error=type(error).__name__+': '+str(error))
        raise
