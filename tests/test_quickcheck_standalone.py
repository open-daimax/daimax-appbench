"""Standalone integration boundaries; no external model calls."""
import asyncio
import json
import threading
from urllib.request import urlopen, Request
from urllib.error import HTTPError
from click.testing import CliRunner
import pytest
from evalapp.quickcheck import evaluate_async, load_config, Settings
from evalapp.quickcheck.cli import main
from evalapp.quickcheck import orchestrator
from evalapp.quickcheck.web import ReviewStore, create_server


def test_configuration_is_independent_and_rejects_retired_modes(tmp_path):
    path = tmp_path/'quickcheck.yaml'
    path.write_text('workspace_root: ./data\nquickcheck:\n  model:\n    name: fixture-model\n    base_url: https://gateway.example/v1\n')
    config = load_config(path)
    assert str(config.output_dir) == 'data/quickcheck'
    assert config.quickcheck.model.name == 'fixture-model'
    with pytest.raises(ValueError):
        Settings(workflow='legacy')


def test_public_api_maps_business_id_and_uses_explicit_settings(monkeypatch, tmp_path):
    async def run(url, **kwargs):
        assert url == 'https://example.com'
        assert kwargs['projectId'] == 'business'
        assert kwargs['output_dir'] == tmp_path
        return {'status': 'completed', 'overall_score': 70}
    monkeypatch.setattr(orchestrator, 'evaluate_async', run)
    result = asyncio.run(evaluate_async('https://example.com', project_id='business', output_dir=tmp_path))
    assert result['overall_score'] == 70


@pytest.mark.parametrize('status,code', [('completed',0), ('partial',2), ('failed',1)])
def test_cli_json_protocol_and_exit_codes(monkeypatch, status, code):
    import evalapp.quickcheck.cli as cli
    def run(**kwargs):
        assert kwargs['project_id'] == 'business'
        return {'schema_version':'4.0','status':status,'overall_score':None}
    monkeypatch.setattr(cli,'evaluate',run)
    result=CliRunner().invoke(main,['evaluate','--request','-'],input=json.dumps({'url':'https://example.com','projectId':'business'}))
    assert result.exit_code == code
    assert json.loads(result.stdout)['status'] == status


def test_cli_errors_do_not_echo_secret_configuration(tmp_path):
    path=tmp_path/'bad.yaml'; path.write_text('quickcheck:\n  model:\n    api_key: PRIVATE_SENTINEL\n    typo: PRIVATE_SENTINEL\n')
    result=CliRunner().invoke(main,['--config',str(path),'evaluate','--url','https://example.com'])
    assert result.exit_code == 1
    assert 'PRIVATE_SENTINEL' not in result.output


def test_demo_job_keeps_failed_evaluation_status(monkeypatch,tmp_path):
    import evalapp.quickcheck.web as web
    async def run(*args,**kwargs):
        record=kwargs['_run_record']
        result={'evaluation_id':record.id,'status':'failed','overall_score':None}
        record.finish(result,{})
        return result
    monkeypatch.setattr(web,'evaluate_async',run)
    store=ReviewStore(Settings(),tmp_path,workers=1,max_queued=0)
    try:
        job=store.submit({'url':'https://example.com','name':None,'projectId':None})
        store.pool.shutdown(wait=True)
        assert store.jobs[job['id']]['status']=='failed'
        assert store.jobs[job['id']]['evaluation_status']=='failed'
    finally:
        store.close()


def test_readonly_model_configuration_and_packaged_page(tmp_path):
    server=create_server(Settings(),tmp_path,port=0,config_path=None)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    base='http://127.0.0.1:'+str(server.server_address[1])
    try:
        response=urlopen(base+'/',timeout=3)
        assert response.status==200 and b'QuickCheck' in response.read()
        assert json.load(urlopen(base+'/api/model-config',timeout=3))['editable'] is False
        request=Request(base+'/api/model-config',data=b'{"name":"other"}',headers={'Content-Type':'application/json'})
        with pytest.raises(HTTPError) as error:
            urlopen(request,timeout=3)
        assert error.value.code==409
    finally:
        server.shutdown();server.server_close();server.store.close()


def test_rejudge_snapshot_is_not_labeled_as_offline_replay(tmp_path,monkeypatch):
    from evalapp.quickcheck.repository import EvaluationRepository
    repo=EvaluationRepository(tmp_path)
    request={'url':'https://example.com','name':None,'projectId':None}
    snapshot=repo.create_snapshot(request,{})
    observations={device:{'readiness':{'scorable':True}} for device in ('mobile','desktop')}
    technical={'devices':{},'evidence':[],'issues':[]}
    snapshot.seal(observations,technical)
    called=[]
    async def judge(*args,**kwargs):
        called.append(True)
        return {},{}
    monkeypatch.setattr(orchestrator,'judge',judge)
    result=asyncio.run(evaluate_async(request['url'],settings=Settings(),output_dir=tmp_path,snapshot_id=snapshot.id))
    assert called == [True]
    assert result['offline_replay'] is False
    assert result['replay_kind']=='snapshot_rejudge'
