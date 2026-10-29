import asyncio,json
import httpx
import pytest
from evalapp.quickcheck.assessment import request_json,model_document,ModelProtocolError
from evalapp.quickcheck.config import Settings


def response(value,**extra):
    return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(value)},'finish_reason':'stop'}],'usage':{'prompt_tokens':10,'completion_tokens':2},**extra})


def test_root_assessment_arrays_preserve_known_judgments():
    rows=[{'id':'composition','quality':{'execution':'considered'}},{'id':'sexual_content','status':'clear'}]
    data,info=model_document(response(rows))
    assert data['items'][0]==rows[0] and data['compliance'][0]==rows[1]
    assert info['adapter']=='assessment_rows_array'
    root={'items':rows[:1],'compliance':rows[1:]}
    assert model_document(response([root]))[0]==root


def test_arbitrary_or_empty_roots_are_not_invented_into_assessments():
    for value in (None,[],{},42,['unknown'],[{'id':'unrecognized'}]):
        data,info=model_document(response(value))
        assert data is None and info['code']=='invalid_model_response'


def settings(retries=2):
    s=Settings(model_max_retries=retries,model_retry_backoff_seconds=.01)
    s.model.name='qwen3.8-flash';s.model.base_url='https://gateway.example/v1';s.model.api_key='test-only'
    return s


def test_empty_output_retries_once_and_retains_failure_diagnostics():
    calls=[];events=[]
    def handle(request):
        calls.append(json.loads(request.content))
        return response(None if len(calls)==1 else {'items':[{'id':'composition','quality':{'execution':'considered'}}]})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle),timeout=2) as client:
            return await request_json(client,settings(),[],'test',attempt_recorder=events.append)
    result=asyncio.run(run())
    assert len(calls)==2 and result['items'][0]['quality']['execution']=='considered'
    assert events[0]['status']=='protocol_error' and events[0]['model_output']=='null'
    assert result['_transport']['attempts']==2 and len(result['_transport']['attempt_usage'])==2


def test_protocol_failure_is_bounded_and_valid_partial_judgments_are_not_retried():
    for retries,expected in ((0,1),(2,2)):
        calls=[]
        async def run():
            def handle(request):calls.append(1);return response(None)
            async with httpx.AsyncClient(transport=httpx.MockTransport(handle),timeout=2) as client:
                return await request_json(client,settings(retries),[],'test')
        with pytest.raises(ModelProtocolError):asyncio.run(run())
        assert len(calls)==expected
    calls=[]
    async def partial():
        def handle(request):calls.append(1);return response({'items':[{'id':'composition','quality':{'execution':'considered'}}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle),timeout=2) as client:
            return await request_json(client,settings(),[],'test')
    assert asyncio.run(partial())['items'][0]['quality']['execution']=='considered'
    assert len(calls)==1


def test_explicit_filtering_is_not_retried_or_bypassed():
    calls=[]
    async def run():
        def handle(request):
            calls.append(1)
            return httpx.Response(200,json={'choices':[{'message':{'content':None,'refusal':'filtered'},'finish_reason':'content_filter'}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle),timeout=2) as client:
            return await request_json(client,settings(),[],'test')
    with pytest.raises(ModelProtocolError,match='model_content_filtered'):asyncio.run(run())
    assert len(calls)==1
