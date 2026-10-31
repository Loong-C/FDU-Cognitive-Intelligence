"""Recompute metrics in a separate directory without rewriting received artifacts."""
import argparse
import hashlib
from importlib.util import spec_from_file_location, module_from_spec
import json
from pathlib import Path
import shutil


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def recompute(source, destination, audit_function=None):
    source, destination = source.resolve(), destination.resolve()
    if source.is_relative_to(destination) or destination.is_relative_to(source):
        raise ValueError('Independent audit output must not overlap received artifacts')
    server_audit=json.loads((source/'audit.json').read_text(encoding='utf-8'))
    if not server_audit['passed']:
        raise ValueError('Server audit has not passed')
    files=[source/'results.json',source/'audit.json']
    files.extend(source/f'seed-{seed}/selection.json' for seed in (42,43,44))
    files.extend(sorted((source/'holdout').rglob('*.json')))
    if any(path.is_symlink() or not path.is_file() for path in files):
        raise ValueError('Missing or linked audit input')
    fingerprint={path.relative_to(source).as_posix():sha(path) for path in files}
    if sha(source/'results.json') != server_audit['results_sha256']:
        raise ValueError('Received result differs from server audit')
    destination.mkdir(parents=True,exist_ok=True)
    manifest=destination/'source_manifest.json'
    if manifest.exists() and json.loads(manifest.read_text()) != fingerprint:
        raise ValueError('Independent audit directory belongs to different inputs')
    for path in files:
        target=(destination/path.relative_to(source)).resolve()
        if not target.is_relative_to(destination):
            raise ValueError('Audit copy escaped destination')
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(path,target)
        if sha(target) != fingerprint[path.relative_to(source).as_posix()]:
            raise ValueError('Independent input copy differs')
    manifest.write_text(json.dumps(fingerprint,sort_keys=True,indent=2)+'\n',encoding='utf-8')
    if audit_function is None:
        spec=spec_from_file_location('independent_metrics_audit',Path(__file__).with_name('audit_finetune27b_v2.py'))
        module=module_from_spec(spec)
        spec.loader.exec_module(module)
        audit_function=module.audit
    result=audit_function(destination)
    if result != server_audit or not result['passed']:
        raise ValueError('Independent recomputation differs from server audit')
    if any(sha(path) != fingerprint[path.relative_to(source).as_posix()] for path in files):
        raise ValueError('Received audit inputs changed during recomputation')
    receipt={'passed':True,'received_input_files':len(files),
             'received_input_bytes_unchanged':True,'audit_directory':str(destination),
             'results_sha256':server_audit['results_sha256']}
    (destination/'recompute.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    return receipt


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    print(json.dumps(recompute(args.source,args.output or args.source.parent/'local_audit'),indent=2))
