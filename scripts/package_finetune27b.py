"""Build an explicit allowlist archive for the remote experiment (never include credentials)."""
from pathlib import Path
import tarfile

root = Path(__file__).resolve().parents[1]
paths = [root / 'src/ab_factcheck' / name for name in [
    '__init__.py', 'finetune27b.py', 'finetune27b_runtime.py', 'metrics.py', 'common.py', 'splitting.py']]
paths += [root / 'prompts/v1' / name for name in ['A0_system.txt', 'A0_user.txt']]
paths += [root / 'data/splits/v1' / dataset / name for dataset in ['basic', 'challenge']
          for name in ['dev.jsonl', 'test.jsonl', 'manifest.json']]
paths += list((root / 'experiments/016_finetune_27b').glob('*.json'))
paths += list((root / 'experiments/016_finetune_27b').glob('*.jsonl'))
archive = root / 'outputs/finetune27b_package.tar.gz'
archive.parent.mkdir(exist_ok=True)
with tarfile.open(archive, 'w:gz') as tar:
    for path in paths:
        tar.add(path, arcname=path.relative_to(root).as_posix(), recursive=False)
print(str(archive))
