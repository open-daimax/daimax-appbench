"""The generated engine/UI/tests must remain the audited standalone export."""
import hashlib
import json
from pathlib import Path


def test_synced_files_match_export_manifest():
    root=Path(__file__).resolve().parents[1]
    manifest=json.loads((root/'docs/quickcheck-sync.json').read_text())
    assert len(manifest['source_revision'])==40
    for name,record in manifest['files'].items():
        path=(root/name).resolve()
        assert path.is_relative_to(root),name
        assert path.is_file(),name
        assert hashlib.sha256(path.read_bytes()).hexdigest()==record['sha256'],name
