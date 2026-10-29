"""Real Chromium evidence and rendered UI. Enable explicitly or in Linux CI."""
import asyncio
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import pytest
from evalapp.quickcheck import evaluate_async, Settings
from evalapp.quickcheck.web import create_server
from evalapp.quickcheck.repository import EvaluationRepository

pytestmark=pytest.mark.skipif(os.environ.get('QUICKCHECK_RUN_BROWSER_TESTS')!='1',reason='Set QUICKCHECK_RUN_BROWSER_TESTS=1 after installing Chromium')


def test_real_browser_capture_scores_and_renders_ui(tmp_path,monkeypatch):
    from tests.test_quickcheck_completion import fixture
    import evalapp.quickcheck.orchestrator as module
    class Page(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_GET(self):
            body=b'<!doctype html><title>Fixture</title><main><h1>QuickCheck fixture</h1><p>Stable page for browser capture.</p><button>Continue</button></main>'
            self.send_response(200);self.send_header('Content-Type','text/html');self.end_headers();self.wfile.write(body)
    site=ThreadingHTTPServer(('127.0.0.1',0),Page)
    threading.Thread(target=site.serve_forever,daemon=True).start()
    async def judge(snapshot,captures,technical,settings,budget_seconds,run,**kwargs):
        assessment,_=fixture()
        ids={d:next(e['id'] for e in technical['evidence'] if e['type']=='screenshot' and e['device']==d) for d in ('mobile','desktop')}
        assessment=json.loads(json.dumps(assessment).replace('"m"',json.dumps(ids['mobile'])).replace('"d"',json.dumps(ids['desktop'])))
        run.write('assessment.raw.json',assessment);run.write('assessment.json',assessment)
        return assessment,{'fixture':True}
    monkeypatch.setattr(module,'judge',judge)
    settings=Settings(minimum_observation_seconds=1,readiness_seconds=3,sample_interval_seconds=.5)
    try:
        result=asyncio.run(evaluate_async('http://127.0.0.1:'+str(site.server_address[1]),settings=settings,output_dir=tmp_path))
        assert result['status']=='completed', result['errors']
        assert result['overall_score'] is not None
        repo=EvaluationRepository(tmp_path)
        assert repo.screenshot(result['evaluation_id'],'mobile.png').stat().st_size>0
        repo.snapshot(result['snapshot_id'])
    finally:
        site.shutdown();site.server_close()
    server=create_server(settings,tmp_path,port=0)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        async def render():
            from playwright.async_api import async_playwright
            async with async_playwright() as playwright:
                browser=await playwright.chromium.launch(headless=True)
                page=await browser.new_page()
                errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                await page.goto('http://127.0.0.1:'+str(server.server_address[1]))
                await page.get_by_role('heading',name='输入链接，快速了解应用质量').wait_for()
                if os.environ.get('QUICKCHECK_SMOKE_SCREENSHOT'):
                    await page.screenshot(path=os.environ['QUICKCHECK_SMOKE_SCREENSHOT'],full_page=True)
                await page.get_by_role('button',name='模型配置',exact=True).click()
                await page.get_by_role('heading',name='模型配置',exact=True).wait_for()
                assert not errors
                await browser.close()
        asyncio.run(render())
    finally:
        server.shutdown();server.server_close();server.store.close()
