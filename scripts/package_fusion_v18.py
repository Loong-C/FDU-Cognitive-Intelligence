"""Freeze executable sources and make an explicit development-only archive."""
from pathlib import Path
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from ab_factcheck import fusion_v18 as f, finetune27b_v2 as c


def package():
    f.verify()
    modules = ['__init__.py', 'common.py', 'metrics.py', 'splitting.py', 'finetune27b_v2.py',
               'finetune27b_engine.py', 'finetune27b_run_v2.py', 'finetune27b_training_v2.py',
               'fusion_v18.py', 'fusion_v18_run.py', 'fusion_v18_training.py', 'fusion_v18_report.py']
    scripts = ['finetune27b_service_guard.py', 'manage_fusion_v18.py', 'audit_fusion_v18.py']
    code = [Path('src/ab_factcheck') / n for n in modules] + [Path('scripts') / n for n in scripts]
    f.immutable(ROOT / f.EXP / 'runtime.json', {'files': {q.as_posix(): c.sha(ROOT / q) for q in code}})
    paths = [*code, *(Path(q) for q in c.read_json(ROOT / f.EXP / 'freeze.json')['files']),
             f.EXP / 'freeze.json', f.EXP / 'runtime.json']
    paths += [p.relative_to(ROOT) for p in (ROOT / f.EXP / 'supervision').rglob('*') if p.is_file()]
    archive = ROOT / 'outputs/fusion_v18.tar.gz'; archive.parent.mkdir(exist_ok=True)
    with tarfile.open(archive, 'w:gz') as tar:
        for path in sorted(set(paths)):
            if path.name == 'test.jsonl' or 'data/raw' in path.as_posix() or path.name.startswith('.env'):
                raise ValueError('Forbidden archive member')
            tar.add(ROOT / path, arcname=path.as_posix(), recursive=False)
    print(archive)
    print('sha256=' + c.sha(archive))


if __name__ == '__main__':
    package()
