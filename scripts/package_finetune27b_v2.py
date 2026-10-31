"""Explicit revision-2 deployment archive; original test files are never packaged."""
from pathlib import Path
import tarfile

root = Path(__file__).resolve().parents[1]
names = ['__init__.py', 'common.py', 'metrics.py', 'splitting.py', 'finetune27b_v2.py',
         'finetune27b_engine.py', 'finetune27b_run_v2.py', 'finetune27b_training_v2.py']
paths = [root / 'src/ab_factcheck' / n for n in names]
paths += [root / 'prompts/v1' / n for n in ['A0_system.txt', 'A0_user.txt']]
paths += [root / f'data/splits/v1/{d}/dev.jsonl' for d in ('basic', 'challenge')]
paths += [root / 'experiments/016_finetune_27b/model_source.json']
paths += [root/'scripts'/name for name in ('finetune27b_service_guard.py',
          'finetune27b_pipeline_v2.py','continue_finetune27b_v2.py','audit_finetune27b_v2.py')]
paths += sorted(p for p in (root / 'experiments/016_finetune_27b/revision_2').iterdir()
                if p.is_file() and p.suffix in ('.json', '.jsonl'))
paths += sorted((root/'experiments/016_finetune_27b/revision_2/draft_source').glob('*.py'))
archive = root / 'outputs/finetune27b_v2.tar.gz'
archive.parent.mkdir(exist_ok=True)
with tarfile.open(archive, 'w:gz') as tar:
    for path in paths:
        if path.name == 'test.jsonl' or path.name.startswith('.env'):
            raise ValueError('Forbidden package member')
        tar.add(path, arcname=path.relative_to(root).as_posix(), recursive=False)
print(archive)
