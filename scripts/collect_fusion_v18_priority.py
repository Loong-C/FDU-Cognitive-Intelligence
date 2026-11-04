"""Collect an audited full-validation milestone while the full experiment continues."""
import argparse
import json
from pathlib import Path
import shlex
import shutil
import sys
import tarfile
import time

from collect_fusion_v18 import transport, ROOT, REMOTE
from ab_factcheck import fusion_v18 as f, fusion_v18_priority as priority, finetune27b_v2 as c


def collect(stage):
    priority.verify()
    # Fixed stage names and verified relative record identities bound the snapshot.
    if stage not in priority.stages(f.verify()):
        raise ValueError('Unknown priority stage')
    remote_code = f'''
import json,tarfile
from pathlib import Path
base=Path({REMOTE!r});out=base/'fusion_v18_runs';stage={stage!r}
folder=out/'priority'/stage
audit=json.loads((folder/'audit.json').read_text())
assert audit['passed']
result=json.loads((folder/'results.json').read_text())
paths=set(folder/n for n in ('results.json','audit.json','RESULTS.md','predictions.csv'))
for identity in result['record_hashes']:
 arm,key=identity.split('/',1)
 candidates=[out/'validation'/kind/arm/(key+'.json') for kind in ('direct','fusion')]
 record_path=next(p for p in candidates if p.exists())
 assert record_path.resolve().is_relative_to((out/'validation').resolve())
 paths.add(record_path)
 record=json.loads(record_path.read_text())
 for ref in record.get('call_refs',[]):
  p=out/ref
  assert p.resolve().is_relative_to((out/'validation').resolve())
  paths.add(p)
target=base/'setup'/('fusion_v18_priority_'+stage+'_results.tar.gz')
with tarfile.open(target,'w:gz') as archive:
 for p in sorted(paths):archive.add(p,arcname=p.relative_to(out).as_posix(),recursive=False)
print(json.dumps({{'files':len(paths),'archive':str(target)}}))
'''
    transport('exec', shlex.quote(REMOTE+'/venv/bin/python')+' -c '+shlex.quote(remote_code))
    folder = ROOT / 'outputs/fusion_v18_collection' / ('priority-'+stage+'-'+str(time.time_ns()))
    folder.mkdir(parents=True)
    archive = folder / 'received.tar.gz'
    transport('download', REMOTE+'/setup/fusion_v18_priority_'+stage+'_results.tar.gz', str(archive))
    received = folder / 'received'; received.mkdir()
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            if not member.isfile() or not (received/member.name).resolve().is_relative_to(received.resolve()):
                raise ValueError('Unsafe archive member')
        tar.extractall(received, filter='data')
    hashes = {p.relative_to(received).as_posix(): c.sha(p) for p in received.rglob('*') if p.is_file()}
    local = folder / 'local_recompute'; shutil.copytree(received, local)
    result = priority.report(local, stage)
    if result != c.read_json(received / 'priority' / stage / 'results.json'):
        raise ValueError('Independent local recomputation differs')
    if hashes != {p.relative_to(received).as_posix(): c.sha(p) for p in received.rglob('*') if p.is_file()}:
        raise ValueError('Received bytes changed')
    publish = ROOT / f.EXP / 'priority_results' / stage
    publish.mkdir(parents=True, exist_ok=True)
    for name in ('results.json', 'RESULTS.md', 'audit.json', 'predictions.csv'):
        source = local / 'priority' / stage / name
        if (publish/name).exists() and (publish/name).read_bytes() != source.read_bytes():
            raise ValueError('Published milestone changed')
        shutil.copy2(source, publish/name)
    receipt = {'stage': stage, 'verified': True, 'descriptive_validation_only': True,
               'archive_sha256': c.sha(archive), 'files': len(hashes), 'published': str(publish),
               'api_restore_not_required_for_intermediate_readonly_collection': True}
    c.save(folder/'manifest.json', hashes); c.save(folder/'completion.json', receipt)
    c.save(ROOT/'outputs/fusion_v18_collection'/('latest_priority_'+stage+'.json'), receipt)
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', choices=list(priority.stages(f.verify())), default='seed42')
    collect(parser.parse_args().stage)
