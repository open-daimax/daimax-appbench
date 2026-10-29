"""LAN entry may submit checks, but cannot access model administration."""
import json
import threading
from types import SimpleNamespace
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from evalapp.quickcheck.config import Settings
from evalapp.quickcheck.web import create_server


def test_shared_entry_uses_same_store_and_blocks_model_configuration():
    submitted=[]
    store=SimpleNamespace(configured=True,repository=SimpleNamespace(cases=lambda:[]),
                          submit=lambda data,**kw:submitted.append(data) or {'id':'test-job','status':'queued'})
    settings=Settings()
    server=create_server(settings,host='127.0.0.1',port=0,store=store,shared=True)
    assert server.store is store
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base='http://127.0.0.1:'+str(server.server_address[1])
    try:
        meta=json.load(urlopen(base+'/api/meta',timeout=3))
        assert meta['shared'] and meta['model_concurrency']==5
        for request in (base+'/api/model-config',Request(base+'/api/model-config',data=b'{"name":"other"}',headers={'Content-Type':'application/json'})):
            try:urlopen(request,timeout=3)
            except HTTPError as error:
                assert error.code==403
                assert json.load(error)['error']=='model_configuration_local_only'
            else:raise AssertionError('Shared model configuration must be blocked')
        request=Request(base+'/api/evaluations',data=b'{"url":"https://example.com"}',headers={'Content-Type':'application/json'})
        response=urlopen(request,timeout=3)
        assert response.status==202 and json.load(response)['id']=='test-job'
        assert submitted[0]['url']=='https://example.com'
        assert submitted[0]['name']=='example.com'
        request=Request(base+'/api/evaluations',data=json.dumps({'url':'https://example.com/index.html?projectId=PROJECT_9','name':'','projectId':''}).encode(),headers={'Content-Type':'application/json'})
        assert urlopen(request,timeout=3).status==202
        assert submitted[-1]['name']=='PROJECT_9' and submitted[-1]['projectId']=='PROJECT_9'
        request=Request(base+'/api/evaluations',data=json.dumps({'url':'https://example.com/?projectId=PROJECT_9','name':'自定义名称','projectId':'custom-id'}).encode(),headers={'Content-Type':'application/json'})
        assert urlopen(request,timeout=3).status==202
        assert submitted[-1]['name']=='自定义名称' and submitted[-1]['projectId']=='custom-id'

    finally:
        server.shutdown();server.server_close();thread.join(timeout=3)
