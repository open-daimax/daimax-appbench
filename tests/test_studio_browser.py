"""Opt-in browser acceptance test. No paid model or device execution."""
import os
from pathlib import Path
import sys
import threading

import pytest

from evalapp.quickcheck.config import Settings
from evalapp.studio.web import create_server

pytestmark = pytest.mark.skipif(os.environ.get('STUDIO_RUN_BROWSER_TESTS') != '1', reason='Enable with STUDIO_RUN_BROWSER_TESTS=1')


def test_console_workflows(tmp_path, monkeypatch):
    from playwright.sync_api import sync_playwright
    project = Path(__file__).resolve().parents[1]
    server = create_server(Settings(), tmp_path, project, port=0)
    original = server.jobs.command

    def command(data, job_id):
        _, workspace = original(data, job_id)  # exercise real input validation
        script = f"from pathlib import Path; import time; p=Path({str(workspace)!r}); p.mkdir(parents=True); print('fixture evaluation started', flush=True); time.sleep(1); (p/'report.html').write_text('<h1>Evaluation fixture report</h1>')"
        return [sys.executable, '-c', script], workspace

    monkeypatch.setattr(server.jobs, 'command', command)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, channel=os.environ.get('STUDIO_BROWSER_CHANNEL'))
            page = browser.new_page(viewport={'width':1440,'height':1080})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{server.server_port}')
            page.get_by_role('heading', name='从第一印象，到完整体验').wait_for()
            page.wait_for_function("[...document.querySelectorAll('.ant-statistic-content-value')].some(e=>Number(e.textContent)>0)")
            if os.environ.get('STUDIO_SCREENSHOT_DIR'):
                page.screenshot(path=os.environ['STUDIO_SCREENSHOT_DIR']+'/studio-overview.png',full_page=True)
            page.get_by_role('button', name='创建完整评测').click()
            page.get_by_label('任务名称').fill('Browser acceptance task')
            page.get_by_label('应用地址').fill('https://example.com')
            page.get_by_label('选择与应用功能对应的标准样本').click()
            page.get_by_label('选择与应用功能对应的标准样本').fill('PomodoroTimer')
            page.locator('.ant-select-item-option-content').filter(has_text='PomodoroTimer').click()
            page.keyboard.press('Escape')
            if os.environ.get('STUDIO_SCREENSHOT_DIR'):
                page.screenshot(path=os.environ['STUDIO_SCREENSHOT_DIR']+'/studio-full.png',full_page=True)
            page.get_by_role('button',name='开始完整评测',exact=True).click()
            page.get_by_role('link',name='打开完整报告').wait_for(timeout=20000)
            assert 'fixture evaluation started' in page.locator('.task-log').inner_text()
            with page.expect_popup() as popup:
                page.get_by_role('link',name='打开完整报告').click()
            popup.value.get_by_role('heading',name='Evaluation fixture report').wait_for()
            popup.value.close()
            page.get_by_role('button',name='Close',exact=True).click()
            page.get_by_role('menuitem',name='快速评测').click()
            page.frame_locator('iframe').get_by_role('heading',name='输入链接，快速了解应用质量').wait_for()
            page.get_by_role('menuitem',name='配置与环境').click()
            page.get_by_text('本地配置',exact=True).wait_for()
            page.get_by_role('menuitem',name='工作台').click()
            page.set_viewport_size({'width':390,'height':844})
            page.wait_for_timeout(350)
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            if os.environ.get('STUDIO_SCREENSHOT_DIR'):
                page.screenshot(path=os.environ['STUDIO_SCREENSHOT_DIR']+'/studio-mobile.png',full_page=True)
            assert not errors, errors
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        server.jobs.close()
        server.store.close()
        thread.join()
