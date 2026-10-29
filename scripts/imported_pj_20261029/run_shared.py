"""供源码包使用的新评测入口，始终写入rerun-目录，保留参考实验。"""
import argparse
from datetime import datetime
from pathlib import Path
import subprocess
import sys

from api_client import ROOT, load_config
from benchmark import read_sources, sha


def main():
    p = argparse.ArgumentParser(description='复现Baseline、通用草稿或v3；默认写入新的结果目录')
    p.add_argument('version', choices=('baseline', 'general', 'v3'))
    p.add_argument('--out', type=Path)
    p.add_argument('--prepare-only', action='store_true', help='只检查数据和准备实验，不发送模型请求')
    p.add_argument('--resume', action='store_true', help='显式继续已有的新实验目录')
    args = p.parse_args()
    out = (args.out or ROOT / 'results' / ('rerun-' + args.version + '-' + datetime.now().strftime('%Y%m%d-%H%M%S'))).resolve()
    if out.parent != ROOT / 'results' or not out.name.startswith('rerun-'):
        p.error('输出须为本项目results下以rerun-开头的目录，以保留参考实验')
    if out.exists() and not args.resume:
        p.error('目录已存在；继续同一实验请加--resume，或改用新目录')
    if args.version == 'baseline':
        if args.prepare_only:
            datasets, prompt, _ = read_sources()
            config = load_config(ROOT / 'config-4096.json')
            print({'prepared': True, 'model': config['model'], 'prompt_sha256': sha(prompt.encode()),
                   'counts': {k: len(v) for k, v in datasets.items()}, 'api_calls': 0})
            return 0
        cmd = [sys.executable, str(ROOT / 'baseline_eval.py'), 'run', '--phase', 'full',
               '--config', str(ROOT / 'config-4096.json'), '--workers', '4', '--out', str(out)]
        if args.resume:
            cmd.append('--resume')
        return subprocess.run(cmd, cwd=ROOT).returncode
    if args.version == 'general':
        import general_full
        general_full.OUT = out
        sys.argv = ['general_full.py'] + (['--prepare'] if args.prepare_only else [])
        general_full.main()
        return 0
    import prompt_v3_full
    sys.argv = ['prompt_v3_full.py', 'prepare' if args.prepare_only else 'run', '--out', str(out)]
    return prompt_v3_full.main()


if __name__ == '__main__':
    raise SystemExit(main())
