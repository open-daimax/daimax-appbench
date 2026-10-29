"""Deterministic capture worker and evidence catalog."""
import asyncio
import hashlib
import json
from .browser import capture, clipped_controls

CAPTURE_FIELDS = ('browser_channel', 'viewports', 'navigation_seconds', 'readiness_seconds', 'minimum_observation_seconds', 'sample_interval_seconds', 'stable_samples', 'screenshot_seconds', 'overflow_tolerance_pixels', 'blank_pixel_stddev', 'layout_tolerance_pixels', 'frame_change_threshold', 'phash_distance', 'dedup_pixel_threshold', 'dedup_local_threshold')


def capture_policy(settings):
    return {key: getattr(settings, key) for key in CAPTURE_FIELDS}


def identifier(kind, device, value):
    return kind + ':' + device + ':' + hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def technical_evidence(captures, errors=None):
    catalog = []
    issues = []
    devices = {}
    for device in ('mobile', 'desktop'):
        c = captures.get(device)
        if c is None:
            devices[device] = {'captured': False}
            continue
        final = c.get('final', {})
        devices[device] = {'captured': True, 'open_failed': c.get('open_failed'), 'readiness': c.get('readiness', {}),
                           'errors': c.get('errors'), 'resource_failures': c.get('resource_failures')}
        selected = c.get('readiness', {}).get('model_screenshots', [s['screenshot'] for s in c.get('samples', [])])
        for filename in selected:
            catalog.append({'id': 'shot:' + device + ':' + filename, 'type': 'screenshot', 'device': device, 'file': filename})
        clips = clipped_controls(final) if final.get('viewport') else []
        if final.get('horizontal_overflow') or clips:
            evidence = {'viewport': final.get('viewport'), 'document_width': final.get('document_width'), 'clipped_controls': clips}
            eid = identifier('geometry', device, evidence)
            fact = {'id': eid, 'type': 'measured_issue', 'device': device, 'owner': device, 'rule_id': 'viewport_geometry',
                    'deduction': 20 if clips else 8, 'evidence': evidence, 'affected_texts': [r['text'] for r in clips]}
            catalog.append(fact); issues.append(fact)
    return {'devices': devices, 'evidence': catalog, 'issues': issues, 'capture_errors': errors or [],
            'scope': 'Observed first-screen window only; missing records remain unknown.'}


async def collect(snapshot, url, settings):
    from playwright.async_api import async_playwright
    captures = {}; errors = []
    playwright = None; browser = None
    try:
        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(headless=True, **({'channel': settings.browser_channel} if settings.browser_channel else {}))
        async def device_capture(device, viewport):
            try:
                observation = await capture(browser, device, viewport, url, snapshot.screenshots, settings)
                captures[device] = observation
            except Exception as exc:
                errors.append({'stage': 'capture', 'device': device, 'code': type(exc).__name__})
        await asyncio.gather(*(device_capture(d, v) for d, v in settings.viewports.items()))
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        errors.append({'stage': 'browser', 'code': type(exc).__name__})
    finally:
        for obj in (browser, playwright):
            if obj is None:
                continue
            closer = obj.close if obj is browser else obj.stop
            try:
                await asyncio.wait_for(closer(), timeout=settings.cleanup_seconds)
            except (Exception, asyncio.CancelledError):
                errors.append({'stage': 'cleanup', 'code': 'bounded_cleanup_incomplete'})
    return captures, technical_evidence(captures, errors)
