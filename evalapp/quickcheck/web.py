"""Optional local review UI. Reuses the evaluator and its portable file storage."""
import json
import os
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlsplit, unquote, parse_qs

import asyncio
from .orchestrator import evaluate_async
from .repository import EvaluationRepository, read_json, safe_path
from .orchestrator import prepare_run, model_gate
from .policy import GROUPS, VERSION, scoring_rules
from .model_settings import public_model, save_model

RUN_ID = re.compile(r'qc_[0-9a-f]{32}')
SCREENSHOT = re.compile(r'(mobile|desktop)(-early|-frame-\d{2,3})?\.png')


def now():
    return datetime.now(timezone.utc).isoformat()


class ReviewStore:
    def __init__(self, settings, output_dir, workers=5, max_queued=4):
        if not 1 <= workers <= 8 or not 0 <= max_queued <= 100:
            raise ValueError('Invalid worker or queue limits')
        self.settings = settings
        if output_dir is None:
            from .paths import default_output_dir
            output_dir=default_output_dir()
        self.root = Path(output_dir)
        self.root.mkdir(parents=True, exist_ok=True)
        self.repository = EvaluationRepository(self.root)
        self.repository.recover_interrupted()
        self.model_slots = model_gate(settings.model_concurrency)
        self.records = {}
        self.job_settings = {}
        self.jobs = {}
        self.lock = threading.Lock()
        self.slots = threading.BoundedSemaphore(workers + max_queued)
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix='quickcheck')
        self.workers = workers
        self.max_queued = max_queued

    @property
    def configured(self):
        m = self.settings.model
        return bool(m.name and m.base_url and (m.api_key or os.environ.get(m.api_key_env)))

    def submit(self, request, snapshot_id=None):
        if not self.slots.acquire(blocking=False):
            return None
        job = {'id': 'job_' + uuid.uuid4().hex, 'status': 'queued', 'request': request,
               'submitted_at': now(), 'started_at': None, 'finished_at': None, 'evaluation_id': None}
        with self.lock:
            self.jobs[job['id']] = job
            # Finished requests live on disk; bound in-memory polling history.
            finished = [k for k, v in self.jobs.items() if v['status'] in ('completed', 'partial', 'failed', 'interrupted')]
            for key in finished[:-200]:
                self.jobs.pop(key, None)
        try:
            record = prepare_run(**request, settings=self.settings, output_dir=self.root, snapshot_id=snapshot_id)
            self.records[job['id']] = record
            self.job_settings[job['id']] = self.settings.model_copy(deep=True)
            job['evaluation_id'] = record.id
            self.pool.submit(self._run, job['id'])
        except Exception:
            self.job_settings.pop(job['id'], None)
            record = self.records.pop(job['id'], None)
            if record:
                record.phase('failed'); record.close()
            self.slots.release()
            with self.lock:
                self.jobs.pop(job['id'], None)
            raise
        return dict(job)

    def _run(self, job_id):
        try:
            with self.lock:
                job = self.jobs[job_id]
                job.update(status='running', started_at=now())
                request = dict(job['request'])
            result = asyncio.run(evaluate_async(request['url'], name=request.get('name'), projectId=request.get('projectId'),
                              settings=self.job_settings[job_id], output_dir=self.root, **({'_run_record': self.records[job_id], '_model_gate': self.model_slots} if job_id in self.records else {})))
            with self.lock:
                job.update(status=result['status'], evaluation_status=result['status'], evaluation_id=result['evaluation_id'], finished_at=now())
        except Exception:
            with self.lock:
                self.jobs[job_id].update(status='failed', error='evaluation_failed', finished_at=now())
        finally:
            self.job_settings.pop(job_id, None)
            record = self.records.pop(job_id, None)
            if record:
                try:
                    manifest = read_json(record.root / 'manifest.json')
                    if manifest['status'] not in ('completed', 'partial', 'failed', 'interrupted'):
                        record.phase('failed')
                finally:
                    record.close()
            self.slots.release()

    def result(self, evaluation_id):
        return self.repository.result(evaluation_id)

    def safe_file(self, evaluation_id, filename):
        if filename.startswith('screenshots/'):
            return self.repository.screenshot(evaluation_id, filename.split('/')[-1])
        path = safe_path(self.repository.run_root(evaluation_id), filename)
        if not path.is_file():
            raise FileNotFoundError()
        return path

    def history(self):
        # The repository owns result indexing; pending runs are exposed separately.
        return [case['latest'] for case in self.repository.cases()
                if case['latest'].get('status') in ('completed', 'partial', 'failed', 'interrupted')][:200]

    def close(self):
        self.pool.shutdown(wait=True, cancel_futures=False)


def create_server(settings, output_dir=None, host='127.0.0.1', port=8765, workers=5, max_queued=4, config_path=None, store=None, shared=False):
    store = store or ReviewStore(settings, output_dir, workers, max_queued)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Target links and business identifiers are private local data.

        def reply(self, status, data, content_type='application/json; charset=utf-8'):
            body = json.dumps(data, ensure_ascii=False).encode() if isinstance(data, (dict, list)) else data
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.end_headers()
            self.wfile.write(body)

        def allowed(self):
            host_header = self.headers.get('Host', '')
            parsed = urlsplit('http://' + host_header)
            if host in ('127.0.0.1', 'localhost', '::1') and parsed.hostname not in ('127.0.0.1', 'localhost', '::1'):
                return False
            origin = self.headers.get('Origin')
            return not origin or urlsplit(origin).netloc == host_header

        def do_GET(self):
            if not self.allowed():
                return self.reply(403, {'error': 'origin_not_allowed'})
            route = unquote(urlsplit(self.path).path)
            if route in ('/', '/quickcheck.html'):
                try:
                    body = files('evalapp.quickcheck').joinpath('static/quickcheck.html').read_bytes()
                except FileNotFoundError:
                    return self.reply(503, {'error': 'ui_not_built'})
                return self.reply(200, body, 'text/html; charset=utf-8')
            if route == '/api/model-config' and shared:
                return self.reply(403, {'error':'model_configuration_local_only'})
            if route == '/api/model-config':
                return self.reply(200, {**public_model(settings), 'editable': config_path is not None})
            if route == '/api/meta':
                return self.reply(200, {'model_configured': store.configured, 'shared': shared, 'model_name': settings.model.name, 'completion_max_attempts': 1,
                     'deadline_seconds': settings.deadline_seconds,
                    'workflow': 'hierarchical', 'groups': GROUPS, 'policy_version': VERSION, 'model_concurrency': settings.model_concurrency,
                    'scoring_rules': scoring_rules(settings), 'viewports': settings.viewports, 'workers': workers, 'max_queued': max_queued})
            if route in ('/api/runs', '/api/cases'):
                return self.reply(200, {'items': store.repository.runs() if route == '/api/runs' else store.repository.cases()})
            if route == '/api/experiments':
                items = [read_json(p) for p in sorted((store.root / 'experiments').glob('exp_*/comparison.json'), key=lambda p: p.stat().st_mtime, reverse=True)]
                return self.reply(200, {'items': items})
            ledger_match = re.fullmatch(r'/api/evaluations/(qc_[0-9a-f]{32})/ledger', route)
            if ledger_match:
                try:
                    return self.reply(200, read_json(store.safe_file(ledger_match[1], 'ledger.json')))
                except (OSError, ValueError):
                    return self.reply(404, {'error': 'ledger_not_found'})
            if route == '/api/evaluations':
                with store.lock:
                    jobs=[dict(j) for j in store.jobs.values() if j['status'] in ('queued','running')]
                    failed=[dict(j) for j in store.jobs.values() if j['status']=='failed'][-5:]
                return self.reply(200, {'items': store.history(),'jobs':jobs+failed})
            if route.startswith('/api/jobs/'):
                with store.lock:
                    job = dict(store.jobs.get(route.rsplit('/', 1)[-1], {}))
                return self.reply(200, job) if job else self.reply(404, {'error': 'job_not_found'})
            match = re.fullmatch(r'/api/evaluations/(qc_[0-9a-f]{32})(?:/screenshots/([^/]+))?', route)
            if match:
                eid, image = match.groups()
                try:
                    if image:
                        if not SCREENSHOT.fullmatch(image):
                            raise FileNotFoundError()
                        return self.reply(200, store.safe_file(eid, 'screenshots/' + image).read_bytes(), 'image/png')
                    return self.reply(200, store.result(eid))
                except (OSError, ValueError):
                    pass
            return self.reply(404, {'error': 'not_found'})

        def do_POST(self):
            if not self.allowed() or self.headers.get('Sec-Fetch-Site') == 'cross-site':
                return self.reply(403, {'error': 'origin_not_allowed'})
            route = urlsplit(self.path).path
            if shared and route not in ('/api/evaluations','/api/replays'):
                return self.reply(403,{'error':'model_configuration_local_only'})
            if route not in ('/api/evaluations', '/api/replays', '/api/experiments', '/api/model-config'):
                return self.reply(404, {'error': 'not_found'})
            if route in ('/api/evaluations','/api/replays') and not store.configured:
                return self.reply(412, {'error': 'model_not_configured'})
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 16384:
                    return self.reply(413, {'error': 'request_too_large'})
                data = json.loads(self.rfile.read(size))
                if not isinstance(data, dict):
                    raise ValueError()
                if route == '/api/model-config':
                    if config_path is None:return self.reply(409, {'error':'configuration_read_only'})
                    with store.lock:
                        if any(j['status'] in ('running','queued') for j in store.jobs.values()):
                            return self.reply(409, {'error':'请等待当前评测完成后再修改模型'})
                        try:updated=save_model(settings,config_path,data)
                        except (ValueError,TypeError):return self.reply(400,{'error':'模型配置无效，请检查名称和接口地址'})
                        except OSError:return self.reply(500,{'error':'配置文件保存失败'})
                    return self.reply(200,{**updated,'editable':True})
                if route == '/api/experiments':
                    return self.reply(201, store.repository.compare(data.get('evaluation_ids')))
                snapshot_id = None
                if route == '/api/replays':
                    source = store.result(data.get('evaluation_id'))
                    snapshot_id = source.get('snapshot_id')
                    if not snapshot_id:
                        return self.reply(409, {'error': 'snapshot_unavailable'})
                    store.repository.snapshot(snapshot_id)
                    data = {key: source.get(key) for key in ('url', 'name', 'projectId')}
                url = data.get('url', '')
                if not isinstance(url, str) or len(url) > 8192:
                    raise ValueError()
                parsed = urlsplit(url)
                if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
                    raise ValueError()
                request = {'url': url}
                for key in ('name', 'projectId'):
                    value = data.get(key)
                    if value is not None and (not isinstance(value, str) or len(value) > 200):
                        raise ValueError()
                    request[key] = value.strip() or None if value else None
                if not request.get('projectId'):
                    inferred = parse_qs(parsed.query).get('projectId', [''])[0]
                    if re.fullmatch(r'[A-Za-z0-9_-]{1,200}', inferred):
                        request['projectId'] = inferred
                if not request.get('name'):
                    request['name'] = request.get('projectId') or parsed.hostname
            except (ValueError, TypeError, OSError):
                return self.reply(400, {'error': 'invalid_request'})
            job = store.submit(request, snapshot_id=snapshot_id)
            return self.reply(202, job) if job else self.reply(429, {'error': 'queue_full'})

    server = ThreadingHTTPServer((host, port), Handler)
    server.store = store
    return server
