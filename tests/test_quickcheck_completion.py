"""Completion must fill holes, never change an existing judgment."""
import asyncio
import copy
from types import SimpleNamespace
from evalapp.quickcheck.completion import normalize, missing_fields, apply_patches
from evalapp.quickcheck.policy import ITEMS, COMPLIANCE
from evalapp.quickcheck.config import Settings


def fixture():
    technical = {'evidence':[{'id':'m','type':'screenshot','device':'mobile'},
                              {'id':'d','type':'screenshot','device':'desktop'}]}
    data={'items':[], 'adjustments':[], 'compliance':[]}
    for owner,spec in ITEMS.items():
        ids=['d' if owner=='desktop' else 'm']
        data['items'].append({'id':owner,'quality':{'execution':'competent','reason':'Existing judgment.', 'evidence_ids':ids,'refinements':[]},
                             'checks':[{'id':cid,'verdict':'yes','reason':'Existing verdict.','evidence_ids':ids} for cid in spec['checks']]})
    next(i for i in data['items'] if i['id']=='creative_expression')['creative_scope']={'tier':'surface_style','domains':['imagery'],'reason':'Local illustrated expression.','evidence_ids':['m']}
    next(i for i in data['items'] if i['id']=='desktop')['usability']={'level':'clear','reason':'Core controls readable.','evidence_ids':['d']}
    for row in data['items']:
        if row['id']!='creative_expression':row['completion_gap']={'status':'observed','reason':'Specific remaining craft issue.','location':'Main task region','evidence_ids':['d' if row['id']=='desktop' else 'm']}
    for key in COMPLIANCE:
        data['compliance'].append({'id':key,'status':'clear','reason':'Observed clear.','evidence_ids':['m']})
    return data,technical


def test_complete_response_does_not_request_any_fields():
    data,t=fixture()
    assert missing_fields(data,t)==[]


def test_patch_can_only_fill_enumerated_holes():
    data,t=fixture();data['items'][0]['quality']['evidence_ids']=[]
    missing=missing_fields(data,t)
    repair={'patches':[
        {'path':['items','composition','quality','execution'],'value':'exceptional'},
        {'path':['adjustments'],'value':[{'kind':'deduction','points':100}]},
        {'path':['items','composition','quality','evidence_ids'],'value':['m']}]}
    merged,audit=apply_patches(data,repair,missing)
    assert merged['items'][0]['quality']['execution']=='competent'
    assert merged['adjustments']==data['adjustments']
    assert merged['items'][0]['quality']['evidence_ids']==['m']
    assert len(audit['rejected_paths'])==2
    assert data['items'][0]['quality']['evidence_ids']==[]


def test_missing_check_and_content_evidence_preserve_other_fields():
    data,t=fixture();check=data['items'][0]['checks'].pop()
    data['compliance'][0]['evidence_ids']=[]
    requested=missing_fields(data,t)
    patches=[{'path':['items','composition','checks',check['id']],'value':check},
             {'path':['compliance','sexual_content','evidence_ids'],'value':['m']}]
    merged,audit=apply_patches(data,{'patches':patches},requested)
    assert missing_fields(merged,t)==[]
    assert merged['compliance'][0]['status']=='clear'
    assert merged['items'][0]['checks'][:2]==data['items'][0]['checks']


def test_duplicate_patch_and_wrong_parent_id_are_rejected():
    data,t=fixture();row=data['items'].pop(0);requested=missing_fields(data,t)
    wrong={**row,'id':'typography'}
    patch={'path':['items','composition'],'value':row}
    merged,audit=apply_patches(data,{'patches':[{'path':['items','composition'],'value':wrong},patch,patch]},requested)
    assert len(audit['rejected_paths'])==2
    assert len([r for r in merged['items'] if r['id']=='composition'])==1


def test_explicit_unknown_is_not_rejudged():
    data,t=fixture();check=data['items'][0]['checks'][0]
    check.update(verdict='unknown',reason='Cannot observe.',evidence_ids=[])
    assert not any(r['path'][:4]==['items','composition','checks',check['id']] for r in missing_fields(data,t))


def test_corresponding_device_evidence_is_required():
    data,t=fixture();mobile=next(r for r in data['items'] if r['id']=='mobile');mobile['quality']['evidence_ids']=['d']
    assert any(r['path']==['items','mobile','quality','evidence_ids'] for r in missing_fields(data,t))


def setup_judge(tmp_path,monkeypatch):
    import evalapp.quickcheck.judge as module
    data,t=fixture()
    for d in ('mobile','desktop'):(tmp_path/(d+'.png')).write_bytes(b'fixture')
    captures={d:{'readiness':{'model_screenshots':[d+'.png']},'samples':[{'screenshot':d+'.png'}]} for d in ('mobile','desktop')}
    writes={};run=SimpleNamespace(write=lambda name,value:writes.__setitem__(name,copy.deepcopy(value)),attempt=lambda event:writes.__setitem__('initial_attempt',event))
    monkeypatch.setattr(module,'messages',lambda *args:[])
    return module,data,t,captures,run,writes


def test_judge_completes_once_with_remaining_budget_and_freezes_ratings(tmp_path,monkeypatch):
    module,data,t,captures,run,writes=setup_judge(tmp_path,monkeypatch)
    data['items'][0]['quality']['evidence_ids']=[];calls=[]
    times=iter([100.,150.]);monkeypatch.setattr(module,'time',SimpleNamespace(monotonic=lambda:next(times,150.)))
    async def request(client,settings,*args,attempt_recorder=None,**kwargs):
        calls.append((client.timeout.read,settings.model_max_retries))
        if len(calls)==1:return {**copy.deepcopy(data),'_transport':{'attempts':1}}
        return {'patches':[{'path':['items','composition','quality','execution'],'value':'exceptional'},
                           {'path':['items','composition','quality','evidence_ids'],'value':['m']}]}
    monkeypatch.setattr(module,'request_json',request)
    result,transport=asyncio.run(module.judge(SimpleNamespace(screenshots=tmp_path),captures,t,Settings(),120,run))
    assert len(calls)==2 and calls[0][0]==105 and calls[1][0]==69.75
    assert calls[1][1]==0
    assert result['items'][0]['quality']['execution']=='competent'
    assert transport['completion']['status']=='completed'
    assert len(transport['completion']['rejected_paths'])==1
    assert 'assessment.raw.json' in writes and 'completion.raw.json' in writes


def test_complete_judge_calls_model_only_once(tmp_path,monkeypatch):
    module,data,t,captures,run,writes=setup_judge(tmp_path,monkeypatch);calls=[]
    async def request(*args,**kwargs):calls.append(1);return data
    monkeypatch.setattr(module,'request_json',request)
    result,transport=asyncio.run(module.judge(SimpleNamespace(screenshots=tmp_path),captures,t,Settings(),120,run))
    assert len(calls)==1 and transport['completion']['status']=='not_needed'


def test_completion_timeout_keeps_original_result_without_third_call(tmp_path,monkeypatch):
    module,data,t,captures,run,writes=setup_judge(tmp_path,monkeypatch);data['compliance'][0]['evidence_ids']=[];calls=[]
    async def request(*args,**kwargs):
        calls.append(1)
        if len(calls)==1:return data
        raise asyncio.TimeoutError()
    monkeypatch.setattr(module,'request_json',request)
    result,transport=asyncio.run(module.judge(SimpleNamespace(screenshots=tmp_path),captures,t,Settings(),120,run))
    assert len(calls)==2 and result==data
    assert transport['completion']['status']=='timeout'


def test_compact_check_patch_and_id_implicit_in_path_are_supported():
    data,t=fixture();check=data['items'][0]['checks'].pop()
    path=['items','composition','checks',check['id']]
    compact=[check[k] for k in ('id','verdict','reason','evidence_ids')]
    merged,audit=apply_patches(data,{'patches':[{'path':path,'value':compact}]},missing_fields(data,t))
    assert missing_fields(merged,t)==[]
    implicit={k:v for k,v in check.items() if k!='id'}
    merged,audit=apply_patches(data,{'patches':[{'path':path,'value':implicit}]},missing_fields(data,t))
    assert missing_fields(merged,t)==[]


def test_queued_time_uses_the_same_total_deadline(tmp_path,monkeypatch):
    from datetime import datetime,timedelta,timezone
    import evalapp.quickcheck.orchestrator as orchestrator
    from evalapp.quickcheck.repository import read_json
    settings=Settings(deadline_seconds=10)
    url='https://example.invalid/'
    record=orchestrator.prepare_run(url,settings=settings,output_dir=tmp_path)
    manifest=read_json(record.root/'manifest.json')
    manifest['created_at']=(datetime.now(timezone.utc)-timedelta(seconds=12)).isoformat()
    record.write('manifest.json',manifest)
    async def forbidden(*args,**kwargs):raise AssertionError('Expired queued work must not capture or call model')
    monkeypatch.setattr(orchestrator,'collect',forbidden)
    monkeypatch.setattr(orchestrator,'judge',forbidden)
    result=asyncio.run(orchestrator.evaluate_async(url,settings=settings,output_dir=tmp_path,_run_record=record))
    assert result['duration_ms']>=12000
    assert any(e['code']=='deadline_exceeded' for e in result['errors'])


def test_shared_loss_only_completes_missing_independent_quality_and_preserves_original():
    data,t=fixture()
    for owner in ('composition','desktop'):
        next(i for i in data['items'] if i['id']==owner)['quality']['reason']='PC端主体过小'
    missing=missing_fields(data,t)
    assert [m['path'] for m in missing]==[['items','composition','independent_quality']]
    value=['refined','Independent grouping is precise.',['m'],['Distinct hierarchy']]
    merged,audit=apply_patches(data,{'patches':[{'path':missing[0]['path'],'value':value}]},missing)
    assert merged['items'][0]['quality']==data['items'][0]['quality']
    assert merged['items'][0]['independent_quality']['execution']=='refined'
    assert missing_fields(merged,t)==[]
