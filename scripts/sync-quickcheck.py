#!/usr/bin/env python3
"""Export a committed standalone QuickCheck checkout into this public repository."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = 'docs/quickcheck-sync.json'
LEGACY = ['desktop.py', 'quality.py', 'runner.py', 'scoring.py', 'workspace.py']

def git(source: Path, *args: str) -> str:
    return subprocess.check_output(['git', '-C', str(source), *args], text=True).strip()

def build_export(source: Path) -> dict[str, bytes]:
    if git(source, 'status', '--porcelain'):
        raise ValueError('Commit standalone changes before syncing a reproducible revision.')
    revision = git(source, 'rev-parse', 'HEAD')
    payload = {}
    origins = {}
    def include(path: Path, destination: str, transform: bool = False) -> None:
        if path.is_symlink() or not path.is_file():
            raise ValueError('Source must contain regular files: ' + str(path.relative_to(source)))
        raw = path.read_bytes()
        data = raw.decode().replace('appbench_quickcheck', 'evalapp.quickcheck').encode() if transform else raw
        payload[destination] = data
        origins[destination] = {'source': str(path.relative_to(source)), 'source_sha256': hashlib.sha256(raw).hexdigest(), 'sha256': hashlib.sha256(data).hexdigest()}
    for path in sorted((source/'src/appbench_quickcheck').glob('*.py')):
        include(path, 'evalapp/quickcheck/' + path.name, True)
    include(source/'src/appbench_quickcheck/static/quickcheck.html', 'evalapp/quickcheck/static/quickcheck.html')
    for path in sorted((source/'ui/src').rglob('*')):
        if path.is_file(): include(path, 'report-ui/src/quickcheck/' + str(path.relative_to(source/'ui/src')))
    for path in sorted((source/'tests').glob('test_*.py')):
        name = path.name
        if name in {'test_standalone.py', 'test_browser_smoke.py'}:
            name = 'test_quickcheck_' + name.removeprefix('test_')
        include(path, 'tests/' + name, True)
    payload[MANIFEST] = (json.dumps({'schema_version':1,'source_revision':revision,
        'source_package':'daimax-appbench-quickcheck','namespace':'evalapp.quickcheck',
        'files':origins},ensure_ascii=False,indent=2,sort_keys=True)+'\n').encode()
    return payload

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path, help='Local committed standalone checkout; no network is used.')
    parser.add_argument('--check', action='store_true', help='Check sync without changing files.')
    args = parser.parse_args()
    try:
        payload = build_export(args.source.resolve())
        previous = json.loads((ROOT/MANIFEST).read_text()) if (ROOT/MANIFEST).exists() else {}
        obsolete = set(previous.get('files', {})) - set(payload)
        obsolete.update('evalapp/quickcheck/' + name for name in LEGACY)
        changed = [name for name,data in payload.items() if not (ROOT/name).is_file() or (ROOT/name).read_bytes()!=data]
        removed = [name for name in obsolete if (ROOT/name).is_file()]
        for name in [*payload, *removed]:
            if not (ROOT/name).resolve().is_relative_to(ROOT):
                raise ValueError('Refusing a destination outside this repository.')
        if args.check:
            if changed or removed:
                print('Out of sync: ' + ', '.join(sorted(changed+removed)))
                return 1
        else:
            for name,data in payload.items():
                path = ROOT/name; path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(data)
            for name in removed:
                if not name.startswith(('evalapp/quickcheck/', 'tests/test_quickcheck_', 'report-ui/src/quickcheck/')):
                    raise ValueError('Refusing to remove a non-exported path.')
                (ROOT/name).unlink()
        print(f'QuickCheck sync: {len(payload)-1} files; revision {json.loads(payload[MANIFEST])["source_revision"][:12]}; mode=' + ('check' if args.check else 'write'))
        return 0
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(2, str(exc)+'\n')

if __name__ == '__main__':
    raise SystemExit(main())
