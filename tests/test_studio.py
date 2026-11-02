"""Studio HTTP boundaries and task lifecycle without model/device calls."""
import json
from pathlib import Path
import subprocess
import sys
import threading
import urllib.request
import urllib.error

import pytest

from evalapp.quickcheck.config import Settings
from evalapp.studio.jobs import Jobs
from evalapp.studio.web import create_server


@pytest.fixture
def server(tmp_path):
    project = Path(__file__).resolve().parents[1]
    srv = create_server(Settings(), tmp_path, project, port=0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    srv.server_close()
    srv.jobs.close()
    srv.store.close()
    thread.join()


def request(server, path, body=None, headers=None):
    req = urllib.request.Request(f'http://127.0.0.1:{server.server_port}' + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={'Content-Type': 'application/json', **(headers or {})})
    try:
        with urllib.request.urlopen(req) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def test_pages_and_shared_history(server):
    assert request(server, '/')[0] == 503  # UI is delivered by the next PR
    assert request(server, '/quickcheck.html')[0] == 200
    assert request(server, '/api/cases')[0] == 200
    status, body = request(server, '/api/studio/samples')
    assert status == 200
    assert any(s['id'] == 'PomodoroTimer' for s in json.loads(body)['items'])
    assert json.loads(request(server, '/api/studio/jobs')[1]) == {'items': []}


@pytest.mark.parametrize('body', [[], {}, {'mode':'url','target':'javascript:alert(1)'},
    {'mode':'workspace','target':'/does-not-exist'},
    {'mode':'url','target':'https://example.com','sample_ids':['../escape']}])
def test_invalid_submission(server, body):
    assert request(server, '/api/studio/jobs', body)[0] == 400
    assert not server.jobs.list()


def test_origin_and_host_protection(server):
    assert request(server, '/api/studio/jobs', {}, {'Origin':'https://evil.example'})[0] == 403
    assert request(server, '/api/studio/meta', headers={'Host':'evil.example'})[0] == 403
    assert request(server, '/api/studio/jobs/../secret')[0] == 404


def test_process_completion_and_failure(tmp_path):
    jobs = Jobs(tmp_path, tmp_path)
    for code, report, expected in [(0, True, 'completed'), (0, False, 'failed'), (1, True, 'failed')]:
        job_id = 'full_' + ('a' if code else 'b' if report else 'c') * 32
        workspace = tmp_path / job_id / 'workspace'
        workspace.mkdir(parents=True)
        job = dict(id=job_id, status='queued', created_at='now', workspace=str(workspace), report=False)
        jobs.save(job)
        script = f"from pathlib import Path; print('test log'); " + (f"Path({str(workspace / 'report.html')!r}).write_text('report'); " if report else '') + f"raise SystemExit({code})"
        jobs.run(job, [sys.executable, '-c', script])
        assert jobs.get(job_id)['status'] == expected
        assert 'test log' in (tmp_path / job_id / 'output.log').read_text()


def test_restart_marks_interrupted(tmp_path):
    jobs = Jobs(tmp_path, tmp_path)
    job = dict(id='full_'+'a'*32, status='running', created_at='now')
    jobs.save(job)
    recovered = Jobs(tmp_path, tmp_path)
    assert recovered.get(job['id'])['status'] == 'interrupted'


def test_no_shell_and_bounded_concurrency(tmp_path, monkeypatch):
    jobs = Jobs(tmp_path, Path(__file__).resolve().parents[1])
    data = dict(mode='url',target='https://example.com/?x=$(touch%20bad)', sample_ids=['PomodoroTimer'])
    cmd, workspace = jobs.command(data, 'full_'+'d'*32)
    assert data['target'] in cmd
    assert '--no-open-report' in cmd
    assert '--output' in cmd
    jobs.active = 'existing'
    with pytest.raises(RuntimeError):
        jobs.submit(data)


def test_report_cannot_escape_workspace(server, tmp_path):
    job_id = 'full_'+'a'*32
    workspace = tmp_path / 'workspace'
    (workspace/'report').mkdir(parents=True)
    (workspace/'report.html').write_text('hello report')
    (tmp_path/'secret.txt').write_text('secret')
    (workspace/'report'/'secret.txt').symlink_to(tmp_path/'secret.txt')
    job = dict(id=job_id,status='completed',created_at='now',workspace=str(workspace),report=True)
    server.jobs.save(job)
    server.jobs.snapshot_report(job)
    assert request(server, f'/studio-reports/{job_id}/report.html')[1] == b'hello report'
    for path in ['report/../../secret.txt', 'report/secret.txt', 'evalapp.yaml']:
        assert request(server, f'/studio-reports/{job_id}/{path}')[0] == 404
