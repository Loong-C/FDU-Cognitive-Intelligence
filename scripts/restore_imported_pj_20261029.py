"""Verify imported materials and restore their original layout under ignored outputs.

This command only reads/writes files. It never executes the imported scripts or
contacts the model service. Original ZIPs are supplied explicitly by the caller.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
NAME = 'imported_pj_20261029'
MANIFEST = ROOT / 'experiments' / NAME / 'import_manifest.json'


def sha(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def within(root: Path, relative: str) -> Path:
    parts = PurePosixPath(relative)
    if parts.is_absolute() or '\\' in relative or ':' in relative or '..' in parts.parts:
        raise ValueError(f'Unsafe relative path: {relative}')
    target = (root / relative).resolve()
    if not target.is_relative_to(root.resolve()) or target == root.resolve():
        raise ValueError(f'Path escapes destination: {relative}')
    return target


def verify_retained(manifest: dict) -> int:
    checked = set()
    for entry in manifest['entries']:
        if 'destination' not in entry:
            continue
        target = within(ROOT, entry['destination'])
        if not target.is_file() or sha(target.read_bytes()) != entry['sha256']:
            raise ValueError(f'Missing or changed retained file: {entry["destination"]}')
        checked.add(target)
    return len(checked)


def prepare_restore(manifest: dict, source: str, archive_path: Path) -> list[tuple[Path, bytes]]:
    expected = manifest['archives'][source]
    if sha(archive_path.read_bytes()) != expected['sha256']:
        raise ValueError(f'ZIP SHA256 does not match the imported {source} archive')
    destination = within(ROOT, f'outputs/{NAME}/{source}')
    files = {e['member']: e for e in manifest['entries'] if e['source'] == source}
    writes = []
    with ZipFile(archive_path) as archive:
        infos = [i for i in archive.infolist() if not i.is_dir()]
        if len(infos) != len(files) or {i.filename for i in infos} != set(files):
            raise ValueError('ZIP members differ from import manifest')
        for info in infos:
            if stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError(f'Symlink ZIP member rejected: {info.filename}')
            target = within(destination, info.filename)
            blob = archive.read(info)
            entry = files[info.filename]
            if len(blob) != entry['bytes'] or sha(blob) != entry['sha256']:
                raise ValueError(f'Member hash mismatch: {info.filename}')
            if target.exists():
                if not target.is_file() or target.read_bytes() != blob:
                    raise ValueError(f'Refusing to overwrite changed runtime file: {target}')
            else:
                writes.append((target, blob))
    return writes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Verify retained files (also performed before any restore).')
    parser.add_argument('--source-zip', type=Path, help='Original scripts and reproduction ZIP.')
    parser.add_argument('--share-zip', type=Path, help='Original group sharing ZIP, including item-level tables.')
    args = parser.parse_args()
    manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
    count = verify_retained(manifest)
    writes = []
    for source, path in [('source', args.source_zip), ('share', args.share_zip)]:
        if path is not None:
            writes.extend(prepare_restore(manifest, source, path))
    # Preflight every supplied archive and existing file before making changes.
    for target, blob in writes:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream:
            stream.write(blob)
    if args.source_zip:
        # Upstream report generator expects this parent directory to exist.
        project = within(ROOT, manifest['policy']['runtime'])
        (project.parent / '笔记').mkdir(exist_ok=True)
        print(f'Runtime: {project}')
    if args.share_zip:
        print(f'Sharing attachments: {ROOT / "outputs" / NAME / "share"}')
    print(f'Verified {count} retained files; restored {len(writes)} files; model API calls: 0.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
