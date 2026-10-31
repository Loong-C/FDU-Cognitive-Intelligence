"""Failure paths must restore the exact service, including killed supervisors."""
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('service_guard', Path(__file__).parents[1]/'scripts/finetune27b_service_guard.py')
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


@pytest.mark.parametrize('outcome', [0, 17, KeyboardInterrupt()])
def test_guard_restores_after_success_failure_and_interrupt(tmp_path, monkeypatch, outcome):
    events = []
    class Process:
        pid = 123
        def wait(self):
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome
    checks = iter([True, False, False])
    monkeypatch.setattr(guard, 'matching', lambda _: next(checks))
    monkeypatch.setattr(guard, 'proc_start', lambda _: '12345')
    monkeypatch.setattr(guard, 'health', lambda *a: events.append('healthy_before'))
    monkeypatch.setattr(guard, 'restore', lambda *a: events.append('restore'))
    monkeypatch.setattr(guard, 'stop_command', lambda *a: events.append('cleanup'))
    monkeypatch.setattr(guard.subprocess, 'Popen', lambda *a, **kw: Process())
    monkeypatch.setattr(guard.signal, 'signal', lambda *a: None)
    monkeypatch.setattr(guard.os, 'kill', lambda *a: events.append('stop_service'))
    args = ({'pid': 456}, tmp_path/'run', ['false'], 'url', tmp_path/'key')
    if isinstance(outcome, BaseException):
        with pytest.raises(KeyboardInterrupt):
            guard.guarded_run(*args)
    else:
        assert guard.guarded_run(*args) == outcome
    assert events == ['healthy_before', 'stop_service', 'cleanup', 'restore']


def test_watchdog_recovers_dead_guard(tmp_path, monkeypatch):
    (tmp_path/'guard_process.json').write_text('{"pid":123}')
    (tmp_path/'snapshot.private.json').write_text('{"pid":456}')
    monkeypatch.setattr(guard, 'matching', lambda _: False)
    events = []
    monkeypatch.setattr(guard, 'stop_command', lambda *a: events.append('stop_child'))
    monkeypatch.setattr(guard, 'restore', lambda *a: events.append('restore'))
    guard.watchdog(tmp_path, 'url', tmp_path/'key')
    assert events == ['stop_child', 'restore']


def test_restoration_reuses_live_restarted_service(tmp_path,monkeypatch):
    directory=tmp_path/'guard';directory.mkdir()
    (directory/'restored_process.json').write_text('{"pid":123,"start_time":"new"}')
    monkeypatch.setattr(guard,'matching',lambda s:s['pid'] == 123)
    monkeypatch.setattr(guard,'health',lambda *a:None)
    def fail(*a,**kw):
        pytest.fail('A live restored service was started again')
    monkeypatch.setattr(guard.subprocess,'Popen',fail)
    guard._restore({'pid':456,'start_time':'old'},directory,'url',tmp_path/'key')
    assert (directory/'restored.json').exists()
    assert guard.json.loads((tmp_path/'current_service.json').read_text())['pid'] == 123


def test_orphan_session_is_found_without_leader_and_pid_reuse_rejected(tmp_path):
    def stat(pid,group,session,start):
        directory=tmp_path/str(pid);directory.mkdir(exist_ok=True)
        fields=['S','1',str(group),str(session)]+['0']*15+[str(start)]
        (directory/'stat').write_text(str(pid)+' (worker with spaces) '+' '.join(fields))
    stat(456,123,123,20)
    stat(789,789,789,10)
    assert guard.command_members({'pid':123,'start_time':'10'},tmp_path)==[456]
    stat(123,123,123,30)
    with pytest.raises(RuntimeError,match='reused'):
        guard.command_members({'pid':123,'start_time':'10'},tmp_path)


def test_cleanup_error_still_attempts_service_restore(tmp_path,monkeypatch):
    (tmp_path/'guard_process.json').write_text('{"pid":123}')
    (tmp_path/'snapshot.private.json').write_text('{"pid":456}')
    monkeypatch.setattr(guard,'matching',lambda _:False)
    restored=[]
    def cleanup(*a):
        raise RuntimeError('Unsafe reused process')
    monkeypatch.setattr(guard,'stop_command',cleanup)
    monkeypatch.setattr(guard,'restore',lambda *a:restored.append(True))
    with pytest.raises(RuntimeError,match='Unsafe'):
        guard.watchdog(tmp_path,'url',tmp_path/'key')
    assert restored==[True]
