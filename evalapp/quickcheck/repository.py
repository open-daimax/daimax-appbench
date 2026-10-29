"""Case/snapshot/run storage. Model judgments never overwrite source evidence."""
from __future__ import annotations
import hashlib
import json
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from .storage import atomic_write_json

RUN_RE = re.compile(r'qc_[0-9a-f]{32}')
SNAP_RE = re.compile(r'snap_[0-9a-f]{32}')
CASE_RE = re.compile(r'case_[0-9a-f]{32}')
TERMINAL = {'completed', 'partial', 'failed', 'interrupted'}
PHASES = {'queued': 0, 'capturing': 1, 'judging': 2, 'scoring': 3}


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def case_identity(request):
    return 'case_' + digest({'url': request.get('url'), 'projectId': request.get('projectId') or ''})[:32]


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def safe_path(root, *parts):
    root = Path(root).resolve()
    path = root.joinpath(*parts).resolve()
    if not path.is_relative_to(root):
        raise FileNotFoundError('outside_workspace')
    return path


def acquire_lease(path, nonblocking=False):
    try:
        import fcntl
    except ImportError:
        return None
    handle = path.open('a+')
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | (fcntl.LOCK_NB if nonblocking else 0))
    except BlockingIOError:
        handle.close()
        return False
    return handle


@dataclass
class Snapshot:
    repository: 'EvaluationRepository'
    id: str
    root: Path

    @property
    def screenshots(self):
        return self.root / 'screenshots'

    def seal(self, observations, technical):
        if (self.root / 'manifest.json').exists():
            raise ValueError('snapshot_already_sealed')
        atomic_write_json(self.root / 'observations.json', observations)
        atomic_write_json(self.root / 'technical.json', technical)
        files = {}
        for path in sorted(self.root.rglob('*')):
            if path.is_symlink():
                raise ValueError('snapshot_symlink')
            if path.is_file():
                files[str(path.relative_to(self.root))] = hashlib.sha256(path.read_bytes()).hexdigest()
        atomic_write_json(self.root / 'manifest.json', {'snapshot_id': self.id, 'sealed_at': now(), 'files': files, 'evidence_sha256': digest(files)})
        return digest(files)


@dataclass
class RunRecord:
    repository: 'EvaluationRepository'
    id: str
    root: Path
    lease: object = field(default=None, repr=False)

    def write(self, filename, data):
        path = safe_path(self.root, filename)
        atomic_write_json(path, data)

    def phase(self, status, **extra):
        manifest = read_json(self.root / 'manifest.json')
        old = manifest['status']
        if old in TERMINAL and status != old:
            raise ValueError('run_already_terminal')
        if status not in PHASES and status not in TERMINAL:
            raise ValueError('invalid_run_phase')
        if old in PHASES and status in PHASES and PHASES[status] < PHASES[old]:
            raise ValueError('run_phase_regression')
        manifest.update(status=status, updated_at=now(), **extra)
        self.write('manifest.json', manifest)
        return manifest

    def attach_snapshot(self, snapshot_id):
        if not SNAP_RE.fullmatch(snapshot_id):
            raise ValueError('invalid_snapshot_id')
        m = read_json(self.root / 'manifest.json')
        self.phase(m['status'], snapshot_id=snapshot_id)

    def attempt(self, event):
        index = event.get('attempt')
        if not isinstance(index, int) or index < 1 or index > 10:
            raise ValueError('invalid_attempt_number')
        # Only the model transport owns this file. No headers, key or request body.
        self.write(f'attempts/{index:02}.json', event)

    def finish(self, result, ledger):
        if (self.root / 'result.json').exists():
            raise ValueError('run_already_finished')
        self.write('ledger.json', ledger)
        self.write('result.json', result)
        self.phase(result['status'], finished_at=now(), result='result.json', ledger='ledger.json')

    def close(self):
        if self.lease:
            self.lease.close()
            self.lease = None


class EvaluationRepository:
    def __init__(self, root=None):
        if root is None:
            from .paths import default_output_dir
            root=default_output_dir()
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def ensure_case(self, request):
        cid = case_identity(request)
        folder = safe_path(self.root, 'cases', cid)
        folder.mkdir(parents=True, exist_ok=True)
        previous = read_json(folder / 'case.json') if (folder / 'case.json').exists() else {}
        atomic_write_json(folder / 'case.json', {**request, 'case_id': cid, 'created_at': previous.get('created_at', now()), 'updated_at': now()})
        return cid

    def create_run(self, request, policy, *, snapshot_id=None):
        policy = json.loads(json.dumps(policy, ensure_ascii=False))
        cid = self.ensure_case(request)
        pid = 'policy_' + digest(policy)
        policy_root = safe_path(self.root, 'policies', pid)
        policy_root.mkdir(parents=True, exist_ok=True)
        existing = policy_root / 'policy.json'
        if existing.exists() and read_json(existing) != policy:
            raise ValueError('policy_fingerprint_conflict')
        if not existing.exists():
            atomic_write_json(existing, policy)
        rid = 'qc_' + uuid.uuid4().hex
        folder = safe_path(self.root, 'runs', rid)
        folder.mkdir(parents=True, exist_ok=False)
        lease = acquire_lease(folder / 'executor.lock')
        record = RunRecord(self, rid, folder, lease)
        record.write('request.json', request)
        record.write('policy.json', policy)
        record.write('manifest.json', {'kind': 'quickcheck_run', 'evaluation_id': rid, 'case_id': cid, 'policy_id': pid,
                                      'snapshot_id': snapshot_id, 'status': 'queued', 'created_at': now(), 'executor_pid': os.getpid()})
        return record

    def create_snapshot(self, request, capture_policy):
        sid = 'snap_' + uuid.uuid4().hex
        folder = safe_path(self.root, 'snapshots', sid)
        (folder / 'screenshots').mkdir(parents=True, exist_ok=False)
        atomic_write_json(folder / 'request.json', request)
        atomic_write_json(folder / 'capture-policy.json', capture_policy)
        return Snapshot(self, sid, folder)

    def snapshot(self, snapshot_id, verify=True):
        if not isinstance(snapshot_id, str) or not SNAP_RE.fullmatch(snapshot_id):
            raise FileNotFoundError('invalid_snapshot_id')
        root = safe_path(self.root, 'snapshots', snapshot_id)
        manifest = read_json(root / 'manifest.json')
        if manifest.get('snapshot_id') != snapshot_id or not isinstance(manifest.get('files'), dict):
            raise ValueError('invalid_snapshot_manifest')
        if verify:
            for name, expected in manifest['files'].items():
                path = safe_path(root, name)
                if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                    raise ValueError('snapshot_integrity_failed')
            if digest(manifest['files']) != manifest.get('evidence_sha256'):
                raise ValueError('snapshot_fingerprint_failed')
        return Snapshot(self, snapshot_id, root)

    def run_root(self, evaluation_id):
        if not isinstance(evaluation_id, str) or not RUN_RE.fullmatch(evaluation_id):
            raise FileNotFoundError('invalid_evaluation_id')
        return safe_path(self.root, 'runs', evaluation_id)

    def result(self, evaluation_id):
        return read_json(safe_path(self.run_root(evaluation_id), 'result.json'))

    def screenshot(self, evaluation_id, filename):
        if not re.fullmatch(r'(mobile|desktop)(-early|-frame-\d{2,3})?\.png', filename):
            raise FileNotFoundError()
        run = self.run_root(evaluation_id)
        manifest = read_json(run / 'manifest.json')
        source = self.snapshot(manifest['snapshot_id']).screenshots
        path = safe_path(source, filename)
        if not path.is_relative_to(self.root.resolve()):
            raise FileNotFoundError()
        if not path.is_file():
            raise FileNotFoundError()
        return path

    def runs(self, include_pending=True):
        records = []
        folders = list((self.root / 'runs').glob('qc_*'))
        for folder in folders:
            if not RUN_RE.fullmatch(folder.name):
                continue
            try:
                if (folder / 'result.json').exists():
                    result = self.result(folder.name)
                elif include_pending:
                    manifest = read_json(folder / 'manifest.json')
                    request = read_json(folder / 'request.json')
                    result = {**request, **manifest, 'score': None, 'groups': {}, 'artifacts': {}}
                else:
                    continue
                manifest = read_json(folder / 'manifest.json') if (folder / 'manifest.json').exists() else {}
                submitted = manifest.get('created_at') or result.get('started_at')
                submitted_time = datetime.fromisoformat(submitted.replace('Z','+00:00')).timestamp() if submitted else (folder / 'result.json').stat().st_mtime
                result = {**result, '_submitted_at': submitted_time, '_stored_at': (folder / ('manifest.json' if (folder / 'manifest.json').exists() else 'result.json')).stat().st_mtime,
                          'case_id': result.get('case_id') or (case_identity(result) if result.get('url') else case_identity(result))}
                records.append(result)
            except (OSError, ValueError, KeyError):
                continue
        return sorted(records, key=lambda r: r['_stored_at'], reverse=True)

    def cases(self):
        groups = {}
        for result in sorted(self.runs(),key=lambda r:r.get('_submitted_at',r.get('_stored_at',0)),reverse=True):
            # Display identity is the exact target URL, independent of optional labels.
            # Fragments and query parameters remain significant application state.
            cid = case_identity({'url': result['url']}) if result.get('url') else result['case_id']
            if cid not in groups:
                groups[cid] = {'case_id': cid, 'url': result.get('url'), 'projectId': result.get('projectId'),
                               'name': result.get('name'), 'latest': result, 'run_count': 0}
            groups[cid]['run_count'] += 1
        return list(groups.values())

    def recover_interrupted(self):
        recovered = []
        for folder in (self.root / 'runs').glob('qc_*'):
            if not RUN_RE.fullmatch(folder.name) or not (folder / 'executor.lock').exists():
                continue
            try:
                lease = acquire_lease(folder / 'executor.lock', nonblocking=True)
                if lease is False or lease is None:
                    continue
                try:
                    manifest = read_json(folder / 'manifest.json')
                    if manifest.get('status') not in TERMINAL:
                        atomic_write_json(folder / 'manifest.json', {**manifest, 'status': 'interrupted', 'updated_at': now(), 'interruption_reason': 'No active execution lease; no automatic resume.'})
                        recovered.append(folder.name)
                finally:
                    lease.close()
            except (OSError, ValueError):
                continue
        return recovered

    def compare(self, evaluation_ids):
        if not isinstance(evaluation_ids, list) or not 2 <= len(evaluation_ids) <= 10 or any(not isinstance(rid, str) for rid in evaluation_ids) or len(set(evaluation_ids)) != len(evaluation_ids):
            raise ValueError('select_two_to_ten_distinct_runs')
        results = [self.result(rid) for rid in evaluation_ids]
        snapshots = {r.get('snapshot_id') for r in results}
        comparable = len(snapshots) == 1 and None not in snapshots
        if comparable:
            self.snapshot(next(iter(snapshots)))
        groups = sorted({key for r in results for key in r.get('groups', {})})
        rows = [{'group': key, 'values': [r.get('groups', {}).get(key, {}).get('score') for r in results]} for key in groups]
        experiment_id = 'exp_' + uuid.uuid4().hex
        comparison = {'experiment_id': experiment_id, 'created_at': now(), 'evaluation_ids': evaluation_ids,
                      'same_snapshot': comparable, 'snapshot_ids': [r.get('snapshot_id') for r in results],
                      'policy_ids': [r.get('policy_id') or r.get('versions', {}).get('policy_sha256') for r in results],
                      'rows': rows, 'runs': [{'evaluation_id': r['evaluation_id'], 'name': r.get('name'), 'policy': r.get('quality_rubric', {}).get('version') or r.get('versions', {}).get('rules'), 'status': r.get('status')} for r in results],
                      'warning': None if comparable else '不同或未知证据快照；差异不能直接归因于规则或模型。'}
        atomic_write_json(safe_path(self.root, 'experiments', experiment_id, 'comparison.json'), comparison)
        return comparison
