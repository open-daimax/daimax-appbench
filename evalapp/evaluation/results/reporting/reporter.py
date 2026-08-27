"""Reporter: 生成评测 HTML 报告（前端单文件模板 + 数据注入）。

报告 UI 与 Web 控制台的评测报告页完全一致：模板 report_template.html 由
studio/frontend 的报告页构建而来（npm run build:report-template，产物提交入库），
本模块只负责准备报告数据 JSON 并注入模板，无任何 HTML 拼装逻辑。
"""

from __future__ import annotations

import json
from pathlib import Path

from ....utils.logging import get_logger
from ..models import EvalRun, build_report_data
from ..comparison.screenshot_extractor import extract_sample_screenshot
from .dataset_catalog import build_dataset_info_for_report
from .e2e_paths import migrate_e2e_report_paths
from .screenshot_export import export_case_screenshots

logger = get_logger(__name__)

# 前端单文件模板（React 报告页构建产物，与 Web 控制台报告页同源）
_TEMPLATE_PATH = Path(__file__).parent / "templates" / "report_template.html"
# 模板中的数据占位（见 studio/frontend/report-standalone.html）
_DATA_PLACEHOLDER = "null /*__REPORT_DATA_PLACEHOLDER__*/"

# 截图文件名解析用平台清单（与 studio 后端 KNOWN_PLATFORMS 保持一致）
_KNOWN_PLATFORMS = ["expo_android", "expo_web", "expo_ios", "android", "ios", "miniprogram", "h5"]


class Reporter:
    """Generates HTML reports from evaluation run data."""

    def generate_html_report(
        self,
        run: EvalRun,
        *,
        dataset_version: str = "",
        eval_version: str = "",
        workspace_dir: Path | None = None,
    ) -> str:
        """Generate a self-contained HTML report for an evaluation run."""
        report_data = build_report_data(
            run, dataset_version=dataset_version, eval_version=eval_version
        )
        report_data_dict = report_data.model_dump()

        # 为每个样本提取TC_LAUNCH截图
        e2e_reports_dir = (workspace_dir / "e2e_reports") if workspace_dir else None
        if e2e_reports_dir and e2e_reports_dir.exists():
            for sr in report_data_dict.get("sample_results", []):
                sample_id = sr.get("sample_id", "")
                platform = sr.get("platform", "")
                screenshot_result = extract_sample_screenshot(e2e_reports_dir, sample_id, platform)
                sr['launch_screenshot'] = screenshot_result.get('screenshot')  # data URL或None
                sr['screenshot_source'] = screenshot_result.get('source')  # 'TC_LAUNCH' 或 'TC001'
                sr['screenshot_reason'] = screenshot_result.get('reason')  # 原因说明

        # 清理 details 字段，避免嵌入JS时引号/转义导致语法错误
        _truncate_case_details(report_data_dict)

        # 迁移旧的绝对路径 report_path 为相对路径
        if workspace_dir is not None:
            migrate_e2e_report_paths(report_data_dict, workspace_dir)

        return self.render_html_from_data(report_data_dict, workspace_dir=workspace_dir)

    def render_html_from_data(
        self,
        report_data: dict,
        *,
        workspace_dir: Path | None = None,
    ) -> str:
        """把已准备好的报告数据字典注入前端模板，返回完整 HTML。

        report_data 结构与 Web 控制台 GET /api/workspaces/{ws}/report 的
        data 字段一致；报告页在本地打开时没有后端可请求，因此本方法把页面
        依赖的工作区/样本集上下文一并注入：
        - static_workspace_id: 工作区目录名（页面标题/路由展示用）
        - static_screenshots: 各样本 screenshots/ 目录清单（相对路径），
          供用例详情/多端对比的截图条使用
        - static_aesthetics_traces: 美观度 trace，按 {样本}{平台} 索引
        - static_command_history: 工作区指令历史（列表）
        - static_dataset_info: 报告涉及样本的样本集元数据（类别/需求/用例定义）

        另外在注入前把 e2e 报告内嵌的用例步骤截图限量落盘（见 screenshot_export），
        并在报告数据未带 execution_overview 时从工作区补齐。
        """
        if workspace_dir is not None:
            report_data.setdefault("static_workspace_id", workspace_dir.name)
            # 必须先落盘再扫描目录，否则本次导出的步骤截图进不了截图清单
            export_case_screenshots(workspace_dir, report_data)
            report_data["static_screenshots"] = _build_static_screenshots(
                workspace_dir, report_data,
            )
            report_data["static_aesthetics_traces"] = _build_aesthetics_traces(
                workspace_dir, report_data,
            )
            report_data["static_command_history"] = _load_command_history(workspace_dir)
            # 评测流程已算过时以其为准，仅在缺失时回读工作区落盘的总览
            if not report_data.get("execution_overview"):
                overview = _read_json(workspace_dir / "execution_overview.json")
                if isinstance(overview, dict) and overview:
                    report_data["execution_overview"] = overview
        report_data.setdefault(
            "static_dataset_info", build_dataset_info_for_report(report_data)
        )
        _normalize_screenshot_urls(report_data)

        data_json = json.dumps(report_data, ensure_ascii=True, default=str)
        # 转义所有 </ 为 <\/，避免 JSON 中的任何闭合标签破坏 HTML 结构
        data_json = data_json.replace("</", "<\\/")
        return _render_html_template(data_json)

    def save_html_report(
        self,
        run: EvalRun,
        output_dir: Path,
        *,
        dataset_version: str = "",
        eval_version: str = "",
    ) -> Path:
        """Generate and save report.html to *output_dir*."""
        html = self.generate_html_report(
            run, dataset_version=dataset_version, eval_version=eval_version,
            workspace_dir=output_dir,
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        html_path = output_dir / "report.html"
        html_path.write_text(html, encoding="utf-8")
        logger.info("HTML report saved to %s", html_path)
        return html_path


# ---------------------------------------------------------------------------
# 模板注入
# ---------------------------------------------------------------------------


def _render_html_template(data_json: str) -> str:
    """加载前端单文件模板并注入报告数据 JSON。"""
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    if _DATA_PLACEHOLDER not in template:
        raise RuntimeError(
            f"报告模板缺少数据占位符 {_DATA_PLACEHOLDER!r}: {_TEMPLATE_PATH}"
            "（模板需由 studio/frontend 执行 npm run build:report-template 重新生成）"
        )
    return template.replace(_DATA_PLACEHOLDER, data_json, 1)


# ---------------------------------------------------------------------------
# 数据准备辅助
# ---------------------------------------------------------------------------


def _truncate_case_details(report_data_dict: dict) -> None:
    """截断用例 details 中的堆栈与超长文本。"""
    for sr in report_data_dict.get("sample_results", []):
        for case in sr.get("e2e_test_cases", []):
            if "details" in case and case["details"]:
                detail = case["details"]
                for marker in ["\n    at ", "\nError:"]:
                    idx = detail.find(marker)
                    if idx > 0:
                        detail = detail[:idx]
                        break
                if len(detail) > 200:
                    detail = detail[:200] + "..."
                case["details"] = detail


def _read_json(path: Path):
    """读取 JSON 文件，不存在或内容损坏时返回 None（报告生成不因此中断）。"""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        logger.debug("读取 %s 失败: %s", path, e)
        return None


def _build_aesthetics_traces(workspace_dir: Path, report_data: dict) -> dict:
    """收集各样本各平台的美观度 trace（``{sample}/aesthetics_trace_{platform}.json``）。

    报告页的美观度明细面板按 {样本}{平台} 两级索引，缺文件的组合直接不出现。
    """
    traces: dict[str, dict[str, dict]] = {}
    for sr in report_data.get("sample_results", []):
        sample_id = sr.get("sample_id", "")
        platform = sr.get("platform", "")
        if not sample_id or not platform:
            continue
        trace = _read_json(
            workspace_dir / sample_id / f"aesthetics_trace_{platform}.json"
        )
        if isinstance(trace, dict):
            traces.setdefault(sample_id, {})[platform] = trace
    return traces


def _load_command_history(workspace_dir: Path) -> list[dict]:
    """读取工作区指令历史，返回报告页直接消费的列表形态。

    这里直读文件而不走 workspace.command_history.list_commands：报告生成对
    工作区应是只读的，不需要为读取加锁，也不应触发损坏文件的备份改名。
    """
    from ....workspace.command_history import COMMAND_HISTORY_FILE

    data = _read_json(workspace_dir / COMMAND_HISTORY_FILE)
    commands = data.get("commands") if isinstance(data, dict) else None
    return commands if isinstance(commands, list) else []


def _normalize_screenshot_urls(report_data: dict) -> None:
    """把 API 形态的截图 URL 归一为工作区相对路径。

    CLI 流程中 launch_screenshot 通常是 data URL；但报告数据若经过其他
    渠道聚合（如控制台导出）可能携带 /api/workspaces/... 形态，静态报告
    无后端可请求，改写为相对路径后可直接访问工作区文件。
    """
    import re

    pattern = re.compile(r"^/api/workspaces/[^/]+/screenshots/([^/]+)/(.+)$")

    def _rewrite(url):
        if isinstance(url, str):
            m = pattern.match(url)
            if m:
                return f"{m.group(1)}/screenshots/{m.group(2)}"
        return url

    for sr in report_data.get("sample_results", []):
        sr["launch_screenshot"] = _rewrite(sr.get("launch_screenshot"))
        for shot in sr.get("screenshots", []) or []:
            if isinstance(shot, dict):
                shot["url"] = _rewrite(shot.get("url"))


def _build_static_screenshots(workspace_dir: Path, report_data: dict) -> dict:
    """扫描各样本 screenshots/ 目录，生成静态报告用截图清单。

    与 studio 后端 GET /samples/{id}/screenshots 的解析规则一致：
    - launch_{platform}.png → TC_LAUNCH 截图
    - {platform}_{tc_id}_step_{n}.png → 用例步骤截图
    url 为相对于工作区根目录（即 report.html 所在目录）的路径。
    """
    manifest: dict[str, list[dict]] = {}
    sample_ids = {
        sr.get("sample_id", "")
        for sr in report_data.get("sample_results", [])
        if sr.get("sample_id")
    }
    for sample_id in sorted(sample_ids):
        screenshots_dir = workspace_dir / sample_id / "screenshots"
        if not screenshots_dir.is_dir():
            continue
        entries: list[dict] = []
        for f in sorted(screenshots_dir.iterdir()):
            if f.suffix.lower() not in (".png", ".jpg", ".jpeg"):
                continue
            name = f.stem
            entry = {
                "filename": f.name,
                "url": f"{sample_id}/screenshots/{f.name}",
                "platform": "",
                "tc_id": "",
                "step": 0,
            }
            if name.startswith("launch_"):
                entry["platform"] = name.replace("launch_", "")
                entry["tc_id"] = "TC_LAUNCH"
            else:
                parts = name.rsplit("_step_", 1)
                if len(parts) == 2:
                    entry["step"] = int(parts[1]) if parts[1].isdigit() else 0
                    prefix = parts[0]
                    for p in _KNOWN_PLATFORMS:
                        if prefix.startswith(p + "_"):
                            entry["platform"] = p
                            entry["tc_id"] = prefix[len(p) + 1:]
                            break
            entries.append(entry)
        if entries:
            manifest[sample_id] = entries
    return manifest
