"""Remote compact status without reading source tests, credentials or private argv."""
import json
from pathlib import Path

base = Path('/root/ab_finetune27b_20261030')
drafts = base/'revision_2_runs/rationale_drafts/drafts'
out = {'drafts_received':len(list(drafts.glob('*_e_*.json'))), 'workers':[]}
for i in range(5):
    log = base/f'logs/revision_2_drafts_{i}.log'
    if log.exists():
        lines = log.read_text(errors='replace').splitlines()
        events = [l for l in lines if l.startswith('{"phase":')]
        out['workers'].append({'worker':i, 'last_event':json.loads(events[-1]) if events else 'loading',
                               'error_tail':lines[-4:] if any('Traceback (most recent call last)' in l for l in lines) else []})
guard = base/'private/guard-parallel-drafts'
out['draft_service_restored'] = (guard/'restored.json').exists()
if (guard/'guard_process.json').exists():
    pid = json.loads((guard/'guard_process.json').read_text())['pid']
    out['guard_running'] = Path('/proc',str(pid)).exists()
if not (base/'revision_2_runs/formal').exists():
    print(json.dumps(out))

formal=base/'revision_2_runs/formal'
if formal.exists():
    state={'formal':True,'smoke_passed':(formal/'smoke/receipt.json').exists(),'seeds':[]}
    controller=base/'private/formal_controller.json'
    if controller.exists():
        process=json.loads(controller.read_text())
        stat=Path('/proc',str(process['pid']),'stat')
        try:
            fields=stat.read_text().rsplit(')',1)[1].split()
            state['controller_running']=(fields[0] != 'Z' and str(fields[19]) == str(process['start_time']))
        except FileNotFoundError:
            state['controller_running']=False
    guards=sorted((base/'private').glob('guard-formal-*'),key=lambda p:p.stat().st_mtime)
    if guards:
        latest=guards[-1]
        state['formal_guard_directory']=latest.name
        state['formal_service_restored']=(latest/'restored.json').exists()
    for seed in (42,43,44):
        directory=formal/f'seed-{seed}'
        steps=sorted((directory/'steps').glob('*.json'))
        state['seeds'].append({'seed':seed,'last_step':json.loads(steps[-1].read_text()) if steps else None,
            'training_complete':(directory/'training_complete.json').exists(),
            'selected':(directory/'selection.json').exists(),
            'validation_received':len(list((formal/f'validation/seed-{seed}').glob('epoch-*/*_e_*.json')))})
    state['baseline_validation_received']=len(list((formal/'validation/baseline').glob('*_e_*.json')))
    state['final_report_exists']=(formal/'results.json').exists()
    state['final_audit_passed']=((formal/'audit.json').exists() and
                                json.loads((formal/'audit.json').read_text()).get('passed',False))
    state['holdout_answers_received']=sum(len(list((formal/'holdout'/arm).glob('*_e_*.json'))) for arm in ('baseline','42','43','44'))
    print(json.dumps(state))
