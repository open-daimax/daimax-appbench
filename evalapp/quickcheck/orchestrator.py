"""Lightweight orchestration of capture worker, one judge and score worker."""
import asyncio
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit
from .config import Settings
from .repository import EvaluationRepository, read_json, now
from .policy import policy_document, VERSION
from .collector import collect, capture_policy
from .judge import judge
from .score_worker import score_assessment
from .harness import StageTimer

_gates = {}
_gate_lock = threading.Lock()


def model_gate(limit):
    with _gate_lock:
        return _gates.setdefault(limit, threading.BoundedSemaphore(limit))


def validate_request(url, name=None, projectId=None):
    if not isinstance(url, str) or len(url) > 8192:
        raise ValueError('invalid_url')
    parsed = urlsplit(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('invalid_url')
    for value in (name, projectId):
        if value is not None and (not isinstance(value, str) or len(value) > 200):
            raise ValueError('invalid_request_label')
    return {'url': url, 'name': name or None, 'projectId': projectId or None}


def prepare_run(url, *, name=None, projectId=None, settings=None, output_dir=None, snapshot_id=None):
    settings = settings.model_copy(deep=True) if settings is not None else Settings()
    request = validate_request(url, name, projectId)
    repository = EvaluationRepository(output_dir)
    if snapshot_id:
        source = repository.snapshot(snapshot_id)
        original = read_json(source.root / 'request.json')
        if original.get('url') != url:
            raise ValueError('snapshot_target_mismatch')
    return repository.create_run(request, policy_document(settings), snapshot_id=snapshot_id)


async def evaluate_async(url, *, name=None, projectId=None, settings=None, output_dir=None, snapshot_id=None, _run_record=None, _model_gate=None):
    settings = settings.model_copy(deep=True) if settings is not None else Settings()
    request = validate_request(url, name, projectId)
    run = _run_record or prepare_run(url, name=name, projectId=projectId, settings=settings, output_dir=output_dir, snapshot_id=snapshot_id)
    repository = run.repository
    manifest = read_json(run.root / 'manifest.json')
    if read_json(run.root / 'request.json') != request:
        run.close(); raise ValueError('prepared_run_request_mismatch')
    snapshot_id = snapshot_id or manifest.get('snapshot_id')
    run.phase(manifest['status'], started_at=now())
    queued_at = datetime.fromisoformat(manifest['created_at'])
    queue_seconds = max(0, (datetime.now(timezone.utc) - queued_at).total_seconds())
    started = time.monotonic() - queue_seconds; captures = {}; technical = {'devices': {}, 'evidence': [], 'issues': []}
    timer = StageTimer(); timer.values['queue'] = round(queue_seconds*1000)
    errors = []; assessment = {}; transport = None; snapshot = None; model_ms = None

    async def pipeline():
        nonlocal captures, technical, assessment, transport, snapshot_id, snapshot, model_ms
        if snapshot_id:
            with timer.measure('snapshot_read'):
                snapshot = repository.snapshot(snapshot_id)
                captures = read_json(snapshot.root / 'observations.json')
                technical = read_json(snapshot.root / 'technical.json')
        else:
            run.phase('capturing')
            snapshot = repository.create_snapshot(request, capture_policy(settings))
            with timer.measure('capture'):
                captures, technical = await collect(snapshot, url, settings)
            with timer.measure('snapshot_write'):
                snapshot.seal(captures, technical)
            snapshot_id = snapshot.id
            run.attach_snapshot(snapshot_id)
        scorable = len(captures) == 2 and all(c.get('readiness', {}).get('scorable') is True for c in captures.values())
        if not scorable:
            errors.append({'stage': 'readiness', 'code': 'snapshot_not_scorable','devices':[{'device':d,'state':c.get('readiness',{}).get('state'),'reason':c.get('readiness',{}).get('reason')} for d,c in captures.items() if c.get('readiness',{}).get('scorable') is not True]})
            return
        run.phase('judging', snapshot_id=snapshot_id)
        gate = _model_gate or model_gate(settings.model_concurrency)
        acquired = False
        waiting_since=time.monotonic()
        try:
            while not acquired:
                acquired = gate.acquire(blocking=False)
                if not acquired:
                    await asyncio.sleep(.05)
            timer.values['model_wait']=round((time.monotonic()-waiting_since)*1000)
            remaining = settings.deadline_seconds - (time.monotonic() - started)
            if remaining <= 0:
                raise asyncio.TimeoutError()
            began = time.monotonic()
            try:
                assessment, transport = await asyncio.wait_for(judge(snapshot, captures, technical, settings, min(settings.model_seconds, remaining), run, timer=timer), timeout=min(settings.model_seconds, remaining))
            finally:
                model_ms = round((time.monotonic() - began) * 1000)
        except Exception as exc:
            code = str(exc) if isinstance(exc, ValueError) and str(exc).startswith(('model_', 'invalid_')) else type(exc).__name__
            errors.append({'stage': 'judge', 'code': code})
            transport = getattr(exc, 'model_transport', None)
        finally:
            if acquired:
                gate.release()

    interrupted = False
    try:
        try:
            await asyncio.wait_for(pipeline(), timeout=max(0, settings.deadline_seconds - queue_seconds))
        except asyncio.CancelledError:
            interrupted = True
            raise
        except asyncio.TimeoutError:
            errors.append({'stage': 'orchestration', 'code': 'deadline_exceeded'})
        except Exception as exc:
            errors.append({'stage': 'snapshot', 'code': str(exc) if isinstance(exc, ValueError) else type(exc).__name__})
        run.phase('scoring', snapshot_id=snapshot_id)
        with timer.measure('scoring'):
            scoring = score_assessment(assessment, technical, read_json(run.root / 'policy.json'))
        complete = all(g['status'] in ('completed', 'not_applicable') for g in scoring['groups'].values())
        judge_failed = not assessment and any(e.get('stage') in {'judge','orchestration','readiness'} for e in errors)
        failure_outcome = 'readiness_failed' if any(e.get('stage')=='readiness' for e in errors) else 'deadline_exceeded' if any(e.get('stage')=='orchestration' for e in errors) else 'judge_failed'
        status = 'failed' if judge_failed else 'completed' if complete else 'partial' if captures else 'failed'
        result = {'schema_version': '4.0', 'evaluation_mode': 'hierarchical', 'assessment_mode': 'single_judge',
                  'evaluation_id': run.id, 'case_id': manifest['case_id'], 'policy_id': manifest['policy_id'], 'snapshot_id': snapshot_id,
                  **request, 'status': status, 'duration_ms': round((time.monotonic() - started) * 1000), 'model_duration_ms': model_ms, 'started_at': read_json(run.root / 'manifest.json').get('started_at'),
                  'timings_ms': dict(timer.values), 'outcome': failure_outcome if judge_failed else 'completed' if complete else 'evidence_or_contract_incomplete',
                  'offline_replay': False, 'replay_kind': 'snapshot_rejudge' if manifest.get('snapshot_id') else None, 'groups': {} if judge_failed else scoring['groups'], 'score': scoring['score'], 'overall_score': scoring['overall_score'], 'overall_weights': scoring['overall_weights'], 'overall_breakdown': scoring['overall_breakdown'],
                  'overall_reason': scoring['overall_reason'], 'gates': scoring['gates'], 'errors': errors + technical.get('capture_errors', []),
                  'review': {'model_transport': transport, 'validation_warnings': scoring['ledger']['warnings']},
                  'quality_rubric': {'version': VERSION}, 'versions': {'rules': VERSION, 'model': settings.model.name, 'policy_sha256': manifest['policy_id'][7:]},
                  'scope': {'first_screen_only': not any(c.get('readiness', {}).get('supplemental_observations') for c in captures.values()), 'supplemental_review': any(c.get('readiness', {}).get('supplemental_observations') for c in captures.values()), 'viewports': settings.viewports},
                  'evidence': technical['evidence'], 'artifacts': {'ledger': 'ledger.json', 'assessment': 'assessment.json', 'raw_assessment': 'assessment.raw.json',
                    'mobile_screenshot': 'mobile.png' if snapshot and (snapshot.screenshots / 'mobile.png').exists() else None,
                    'desktop_screenshot': 'desktop.png' if snapshot and (snapshot.screenshots / 'desktop.png').exists() else None}}
        with timer.measure('persistence'):
            run.finish(result, scoring['ledger'])
        timer.values['total']=round((time.monotonic()-started)*1000)
        result['duration_ms']=timer.values['total']
        result['timings_ms']=dict(timer.values)
        run.write('stage_timings.json', timer.values)
        run.write('result.json',result)
        return result
    finally:
        if interrupted:
            run.phase('interrupted', interruption_reason='Execution cancelled; no automatic resume.')
        run.close()
