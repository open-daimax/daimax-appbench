import copy
import pytest
from evalapp.quickcheck.harness import EvidenceCodec,StageTimer,initial_budget
from evalapp.quickcheck.completion import normalize,missing_fields,apply_patches
from tests.test_quickcheck_completion import fixture


def test_keyed_checks_are_canonicalized_before_completion():
    data,t=fixture();raw=copy.deepcopy(data)
    raw['items']={r['id']:{k:v for k,v in r.items() if k!='id'} for r in raw['items']}
    for row in raw['items'].values():
        row['checks']={r['id']:[r['verdict'],r['reason'],r['evidence_ids']] for r in row['checks']}
    raw['compliance']={r['id']:[r['status'],r['reason'],r['evidence_ids']] for r in raw['compliance']}
    assert normalize(raw)==data
    assert missing_fields(normalize(raw),t)==[]
    assert isinstance(raw['items']['composition']['checks'],dict)


def test_partial_keyed_check_repairs_only_missing_leaf():
    data,t=fixture();data['items'][0]['checks']={r['id']:{'verdict':r['verdict'],'reason':r['reason'],'evidence_ids':r['evidence_ids']} for r in data['items'][0]['checks']}
    data['items'][0]['checks']['subject'].pop('evidence_ids')
    normalized=normalize(data);missing=missing_fields(normalized,t)
    assert [r['path'] for r in missing]==[['items','composition','checks','subject','evidence_ids']]
    patched,audit=apply_patches(normalized,{'patches':[{'path':missing[0]['path'],'value':['m']}]},missing)
    assert missing_fields(patched,t)==[] and patched['items'][0]['checks'][0]['verdict']=='yes'


def test_conflicting_explicit_id_is_preserved_for_validation():
    data,t=fixture();data['items'][0]['checks']={'subject':{'id':'grouping','verdict':'yes','reason':'Known','evidence_ids':['m']}}
    normalized=normalize(data)
    assert normalized['items'][0]['checks'][0]['id']=='grouping'
    assert missing_fields(normalized,t)


def test_alias_roundtrip_preserves_judgments():
    data,t=fixture();codec=EvidenceCodec(t['evidence']);encoded=codec.encode(data)
    assert encoded['items'][0]['quality']['evidence_ids']==['@e0']
    assert codec.decode(encoded)==data
    assert codec.decode({'evidence_ids':['@invented']})=={'evidence_ids':['@invented']}


def test_failures_are_timed_and_primary_budget_is_not_artificially_capped():
    timer=StageTimer()
    with pytest.raises(RuntimeError):
        with timer.measure('inference'):raise RuntimeError('provider timeout')
    assert timer.values['inference']>=0
    assert initial_budget(120)==105
    assert 0<initial_budget(8)<8


def test_provider_timeout_is_a_failed_request_not_missing_evidence(tmp_path,monkeypatch):
    import asyncio
    import evalapp.quickcheck.orchestrator as module
    from evalapp.quickcheck.config import Settings
    async def collect(*args,**kwargs):
        return {d:{'readiness':{'scorable':True}} for d in ('mobile','desktop')},{'devices':{d:{'captured':True} for d in ('mobile','desktop')},'evidence':[],'issues':[]}
    async def judge(*args,**kwargs):raise asyncio.TimeoutError()
    monkeypatch.setattr(module,'collect',collect);monkeypatch.setattr(module,'judge',judge)
    result=asyncio.run(module.evaluate_async('https://example.invalid/',settings=Settings(),output_dir=tmp_path))
    assert result['status']=='failed' and result['outcome']=='judge_failed'
    assert result['groups']=={} and result['overall_score'] is None
    assert result['errors']==[{'stage':'judge','code':'TimeoutError'}]
    assert result['timings_ms']['capture']>=0 and result['timings_ms']['total']>=0


def test_shared_layout_metadata_does_not_invalidate_positive_independent_judgment():
    from evalapp.quickcheck.attribution import layout_context_required
    row={'quality':{'execution':'competent','reason':'桌面端留白过大'},'independent_quality':{'execution':'competent','reason':'移动端构图稳定，分区关系清晰'}}
    assert not layout_context_required('composition',row,True)
    row['independent_quality']['reason']='移动端主体过小，独立影响阅读'
    assert layout_context_required('composition',row,True)


def test_record_replay_preserves_source_and_never_requires_model_credentials(tmp_path):
    import hashlib
    from evalapp.quickcheck.repository import EvaluationRepository,read_json
    from evalapp.quickcheck.policy import policy_document
    from evalapp.quickcheck.config import Settings
    from evalapp.quickcheck.replay import replay_record
    settings=Settings();repo=EvaluationRepository(tmp_path);a,t=fixture()
    t['devices']={d:{'captured':True,'open_failed':False,'readiness':{'scorable':True},'errors':[],'resource_failures':[]} for d in ('mobile','desktop')}
    t['issues']=[]
    request={'url':'https://example.invalid/','name':'fixture','projectId':None}
    snapshot=repo.create_snapshot(request,{})
    snapshot.seal({},t)
    source=repo.create_run(request,policy_document(settings),snapshot_id=snapshot.id)
    source.write('assessment.json',a)
    source.finish({**request,'evaluation_id':source.id,'snapshot_id':snapshot.id,'status':'partial','duration_ms':53000,'timings_ms':{'inference':45000}}, {})
    source.close();path=source.root/'assessment.json';before=hashlib.sha256(path.read_bytes()).hexdigest()
    replayed=replay_record(source.id,settings=settings,output_dir=tmp_path)
    assert replayed['status']=='completed' and replayed['overall_score'] is not None
    assert replayed['evaluation_id']!=source.id and replayed['source_duration_ms']==53000
    assert hashlib.sha256(path.read_bytes()).hexdigest()==before
    assert replayed['timings_ms']['inference']==45000


def test_unready_snapshot_is_reported_as_capture_readiness_not_model_failure(tmp_path,monkeypatch):
    import asyncio
    import evalapp.quickcheck.orchestrator as module
    from evalapp.quickcheck.config import Settings
    async def collect(*args,**kwargs):
        return {d:{'readiness':{'scorable':False,'state':'unsettled','reason':'Still loading'}} for d in ('mobile','desktop')},{'devices':{},'evidence':[],'issues':[]}
    async def forbidden(*args,**kwargs):raise AssertionError('Unready capture must not invoke model')
    monkeypatch.setattr(module,'collect',collect);monkeypatch.setattr(module,'judge',forbidden)
    result=asyncio.run(module.evaluate_async('https://example.invalid/',settings=Settings(),output_dir=tmp_path))
    assert result['status']=='failed' and result['outcome']=='readiness_failed'
    assert result['errors'][0]['stage']=='readiness'
    assert len(result['errors'][0]['devices'])==2
