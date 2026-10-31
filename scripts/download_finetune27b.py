"""Download the frozen original checkpoint; verify every file against publisher SHA256."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import time
import urllib.parse
import urllib.request


def sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def download(manifest, directory):
    directory.mkdir(parents=True, exist_ok=True)
    def one(entry):
        name = entry['Path']
        if Path(name).name != name:
            raise ValueError('Only flat model files are accepted')
        path = directory / name
        if path.exists():
            if path.stat().st_size != entry['Size'] or sha256(path) != entry['Sha256']:
                raise ValueError('Existing file differs: ' + name)
            print(json.dumps({'verified_existing': name}), flush=True)
            return
        url = 'https://modelscope.cn/api/v1/models/Qwen/Qwen3.8-27B/repo?' + urllib.parse.urlencode(
            {'Revision': entry['Revision'], 'FilePath': name})
        temporary = path.with_name(name + '.partial')
        for attempt in range(3):
            try:
                h = hashlib.sha256()
                with urllib.request.urlopen(url, timeout=120) as response, temporary.open('wb') as f:
                    while chunk := response.read(8 * 1024 * 1024):
                        f.write(chunk)
                        h.update(chunk)
                if temporary.stat().st_size != entry['Size'] or h.hexdigest() != entry['Sha256']:
                    raise ValueError('Downloaded size/hash mismatch: ' + name)
                temporary.replace(path)
                print(json.dumps({'downloaded': name, 'bytes': entry['Size']}), flush=True)
                return
            except Exception as error:
                print(json.dumps({'file': name, 'attempt': attempt + 1, 'error': str(error)}), flush=True)
                if attempt == 2:
                    raise
                time.sleep(2)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(one, manifest['files']))
    receipt = {'model_id': manifest['model_id'], 'files': manifest['files'], 'all_verified': True}
    (directory / 'verified_download.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print('ALL_FILES_VERIFIED', flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('manifest', type=Path)
    p.add_argument('destination', type=Path)
    args = p.parse_args()
    download(json.loads(args.manifest.read_text()), args.destination)
