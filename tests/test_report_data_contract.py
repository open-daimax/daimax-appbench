"""本地报告的注入数据契约测试。

报告页（``report-ui/``）不再有后端接口，页面上的所有能力都依赖生成时注入到
``window.__REPORT_DATA__`` 的字段。前端唯一的读取入口是 ``report-ui/src/data/local.js``，
因此这里从两侧对齐：

* 生成侧：``Reporter.render_html_from_data`` 必须注入约定的 ``static_*`` 字段；
* 消费侧：``local.js`` 里读到的每个 ``static_*`` 字段都必须被生成侧注入
  （新增一个前端字段却忘了写生成逻辑，会在这里失败）。

外加一个模板守卫：单文件模板必须带数据占位符，且不能残留 ``/api/`` 请求路径
（残留意味着模板是控制台版本，本地打开会静默失败）。
"""

from __future__ import annotations

import base64
import json
import re
import struct
import zlib
from pathlib import Path

import pytest

from evalapp.evaluation.results.reporting.reporter import Reporter
from evalapp.utils.paths import set_project_root

_REPO_ROOT = Path(__file__).resolve().parents[1]
_TEMPLATE = (
    _REPO_ROOT / "evalapp/evaluation/results/reporting/templates/report_template.html"
)
_LOCAL_JS = _REPO_ROOT / "report-ui/src/data/local.js"

# 生成侧必须注入的字段（与 render_html_from_data 的文档串一一对应）
_REQUIRED_KEYS = {
    "static_workspace_id",
    "static_screenshots",
    "static_aesthetics_traces",
    "static_command_history",
    "static_dataset_info",
}


def _png(width: int, height: int) -> bytes:
    """生成一张全白 PNG。

    提取器会按真实宽高过滤小于 200px 的装饰图，因此测试图必须带真实 IHDR。
    """
    raw = b"".join(b"\x00" + b"\xff" * (width * 3) for _ in range(height))

    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body))
            + kind
            + body
            + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def _fake_e2e_html(step_count: int) -> str:
    """构造带内嵌 base64 截图的 midscene 形态 e2e 报告。"""
    payload = base64.b64encode(_png(240, 400)).decode()
    frames = "".join(
        f'<div data-id="frame-{i}">data:image/png;base64,{payload}</div>'
        for i in range(1, step_count + 1)
    )
    return f"<html><body>{frames}</body></html>"


@pytest.fixture(autouse=True)
def repo_project_root():
    """把项目根钉在本仓。

    样本集元数据取自 ``get_project_root() / "dataset"``，而项目根是全局单例，
    不钉住就会被其他测试的临时目录干扰。
    """
    set_project_root(_REPO_ROOT)
    yield


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """构造一个最小但结构真实的工作区。

    覆盖两种 e2e 报告布局中的样本级布局（目录名不带样本前缀），并放置美观度
    trace、指令历史、执行总览各一份。
    """
    ws = tmp_path / "app_h5_20260824_014219"
    ws.mkdir()

    case_dir = ws / "PlantDiary/e2e_reports/h5_TC001_20260824_052204"
    case_dir.mkdir(parents=True)
    (case_dir / "report.html").write_text(_fake_e2e_html(12), encoding="utf-8")

    shots_dir = ws / "PlantDiary/screenshots"
    shots_dir.mkdir(parents=True)
    (shots_dir / "launch_h5.png").write_bytes(_png(240, 400))

    (ws / "PlantDiary/aesthetics_trace_h5.json").write_text(
        json.dumps(
            {
                "platform": "h5",
                "rule_version": "2.1",
                "parsed_result": {"overall": 7.5, "dimensions": {"typography": 8}},
                "selected_frames": ["/abs/cache/frame_1.jpg"],
                "frame_count": 2,
            }
        ),
        encoding="utf-8",
    )

    (ws / "command_history.json").write_text(
        json.dumps(
            {
                "workspace_id": ws.name,
                "commands": [
                    {
                        "command_id": "cmd_1",
                        "type": "generate_and_test",
                        "status": "completed",
                        "duration_ms": 1000,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    (ws / "execution_overview.json").write_text(
        json.dumps({"error_429": {}, "sub_agents": {}, "review_issues": {}}),
        encoding="utf-8",
    )
    return ws


def _report_data() -> dict:
    """一份最小报告数据：单样本单平台单用例，report_path 为不可访问的绝对路径。"""
    return {
        "meta": {"run_id": "run-1", "platform": ["h5"]},
        "summary": {},
        "sample_results": [
            {
                "sample_id": "PlantDiary",
                "platform": "h5",
                "aesthetics_score": 7.5,
                "e2e_test_cases": [
                    {
                        "test_case_id": "TC001",
                        "status": "PASS",
                        "report_path": "/Users/runner/.cache/midscene/report.html",
                    }
                ],
            }
        ],
        "excluded_samples": [],
    }


class TestTemplateGuard:
    def test_template_has_data_placeholder(self):
        html = _TEMPLATE.read_text(encoding="utf-8")
        assert "null /*__REPORT_DATA_PLACEHOLDER__*/" in html

    def test_template_has_no_backend_requests(self):
        """模板里出现 /api/ 说明打包了控制台版本，本地打开会请求不到数据。"""
        html = _TEMPLATE.read_text(encoding="utf-8")
        assert "/api/workspaces/" not in html


class TestInjectedFields:
    def test_all_required_keys_injected(self, workspace: Path):
        data = _report_data()
        Reporter().render_html_from_data(data, workspace_dir=workspace)
        assert _REQUIRED_KEYS <= data.keys()
        assert data["static_workspace_id"] == workspace.name

    def test_execution_overview_loaded_from_workspace(self, workspace: Path):
        data = _report_data()
        Reporter().render_html_from_data(data, workspace_dir=workspace)
        assert set(data["execution_overview"]) == {
            "error_429",
            "sub_agents",
            "review_issues",
        }

    def test_command_history_is_a_list(self, workspace: Path):
        data = _report_data()
        Reporter().render_html_from_data(data, workspace_dir=workspace)
        history = data["static_command_history"]
        assert isinstance(history, list) and len(history) == 1
        assert history[0]["type"] == "generate_and_test"

    def test_aesthetics_trace_keyed_by_sample_and_platform(self, workspace: Path):
        data = _report_data()
        Reporter().render_html_from_data(data, workspace_dir=workspace)
        trace = data["static_aesthetics_traces"]["PlantDiary"]["h5"]
        assert trace["parsed_result"]["overall"] == 7.5

    def test_dataset_info_shape(self, workspace: Path):
        data = _report_data()
        Reporter().render_html_from_data(data, workspace_dir=workspace)
        info = data["static_dataset_info"]
        assert set(info) == {"categories", "samples", "test_cases"}
        # PlantDiary 在本仓 dataset/ 中存在，应带出中文标题与用例定义
        assert info["samples"]["PlantDiary"]["title"]
        assert info["test_cases"]["PlantDiary"]

    def test_screenshot_entries_are_workspace_relative(self, workspace: Path):
        data = _report_data()
        Reporter().render_html_from_data(data, workspace_dir=workspace)
        entries = data["static_screenshots"]["PlantDiary"]
        assert entries, "落盘后应至少扫描到启动截图"
        for e in entries:
            assert set(e) == {"filename", "url", "platform", "tc_id", "step"}
            assert e["url"] == f"PlantDiary/screenshots/{e['filename']}"
            assert not e["url"].startswith("/")
            assert (workspace / e["url"]).is_file()

    def test_case_screenshots_exported_and_indexed(self, workspace: Path):
        """步骤截图应按 {platform}_{tc}_step_{n} 落盘，并能反解出 tc_id/step。"""
        data = _report_data()
        Reporter().render_html_from_data(data, workspace_dir=workspace)
        steps = [
            e
            for e in data["static_screenshots"]["PlantDiary"]
            if e["tc_id"] == "TC001"
        ]
        assert 0 < len(steps) <= 8, "每用例落盘数应受上限约束"
        assert all(e["platform"] == "h5" and e["step"] > 0 for e in steps)

    def test_launch_screenshot_indexed(self, workspace: Path):
        data = _report_data()
        Reporter().render_html_from_data(data, workspace_dir=workspace)
        launch = [
            e
            for e in data["static_screenshots"]["PlantDiary"]
            if e["tc_id"] == "TC_LAUNCH"
        ]
        assert len(launch) == 1
        assert launch[0]["platform"] == "h5"


class TestFrontendContract:
    def test_local_js_reads_only_injected_fields(self, workspace: Path):
        """local.js 里读的每个 static_* 字段都必须由生成侧注入。"""
        source = _LOCAL_JS.read_text(encoding="utf-8")
        # 只取属性访问形态（data?.static_xxx），避免命中注释里的说明文字
        referenced = set(re.findall(r"\.(static_[a-z_]+)", source))
        assert referenced, "未从 local.js 解析出任何注入字段，正则或文件结构已变"

        data = _report_data()
        Reporter().render_html_from_data(data, workspace_dir=workspace)
        missing = referenced - data.keys()
        assert not missing, f"local.js 读取了生成侧未注入的字段: {sorted(missing)}"

    def test_report_paths_migrated_to_relative_files(self, workspace: Path):
        """report_path 必须落到导出目录内的真实文件，否则“查看详细报告”是死链。"""
        from evalapp.evaluation.results.reporting.e2e_paths import (
            migrate_e2e_report_paths,
        )

        data = _report_data()
        migrate_e2e_report_paths(data, workspace)
        path = data["sample_results"][0]["e2e_test_cases"][0]["report_path"]
        assert not path.startswith("/")
        assert (workspace / path).is_file()
