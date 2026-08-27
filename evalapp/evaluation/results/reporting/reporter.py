"""Reporter: 生成评测 HTML 报告（前端单文件模板 + 数据注入）。

模板 report_template.html 由本仓 report-ui/ 构建而来（npm run build:template，
产物提交入库，使用者无需 Node 环境），本模块只负责准备报告数据 JSON 并注入
模板，无任何 HTML 拼装逻辑。

本地报告是纯静态只读产物：凡是数据已在工作区内的能力（美观度 trace、执行
总览、操作历史、用例步骤截图……）都必须在此一并注入，报告页运行时不会发起
任何请求。
"""

from __future__ import annotations

import json
from pathlib import Path

from ....utils.logging import get_logger
from ..models import EvalRun, build_report_data
from ..comparison.screenshot_extractor import extract_sample_screenshot
from .dataset_catalog import build_dataset_info_for_report
from .screenshot_export import export_case_screenshots

logger = get_logger(__name__)

# 前端单文件模板（report-ui/ 构建产物）
_TEMPLATE_PATH = Path(__file__).parent / "templates" / "report_template.html"
# 模板中的数据占位（见 report-ui/index.html）
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
            _migrate_report_paths(report_data_dict, workspace_dir)

        return self.render_html_from_data(report_data_dict, workspace_dir=workspace_dir)

    def render_html_from_data(
        self,
        report_data: dict,
        *,
        workspace_dir: Path | None = None,
    ) -> str:
        """把已准备好的报告数据字典注入前端模板，返回完整 HTML。

        report_data 结构与 Web 控制台 GET /api/workspaces/{ws}/report 的
        data 字段一致；本方法额外注入本地报告所需的工作区数据：
        - static_workspace_id: 工作区目录名（页面标题展示用）
        - static_screenshots: 各样本 screenshots/ 目录清单（相对路径），
          供用例详情/多端对比的截图条使用
        - static_aesthetics_traces: 各样本美观度评测 trace（关键截图/五维明细）
        - static_command_history: 工作区指令历史
        - execution_overview: 执行总览（缺失时从工作区文件补齐）
        - static_dataset_info: 本地 dataset/ 的样本集元数据（分组/中文名/需求/用例定义）
        """
        report_data["static_dataset_info"] = build_dataset_info_for_report(report_data)
        if workspace_dir is not None:
            report_data.setdefault("static_workspace_id", workspace_dir.name)
            # 先落盘用例步骤截图，再扫描目录，两步共用同一套文件名约定
            export_case_screenshots(workspace_dir, report_data)
            report_data["static_screenshots"] = _build_static_screenshots(
                workspace_dir, report_data,
            )
            report_data["static_aesthetics_traces"] = _build_aesthetics_traces(
                workspace_dir, report_data,
            )
            report_data["static_command_history"] = _load_command_history(workspace_dir)
            if not report_data.get("execution_overview"):
                overview = _load_json(workspace_dir / "execution_overview.json")
                if overview:
                    report_data["execution_overview"] = overview
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
            "（模板需在 report-ui/ 执行 npm run build:template 重新生成）"
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

    与 static_screenshots 的文件名约定一致：
    - launch_{platform}.png → TC_LAUNCH 截图
    - {platform}_{tc_id}_step_{n}.png → 用例步骤截图（由 screenshot_export 落盘）
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


def _load_json(path: Path):
    """读取工作区 JSON 文件，缺失或损坏时返回 None（不阻断报告生成）。"""
    if not path.is_file():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        logger.debug("读取 %s 失败: %s", path, e)
        return None


def _build_aesthetics_traces(workspace_dir: Path, report_data: dict) -> dict:
    """收集各样本各平台的美观度 trace（{sample: {platform: trace}}）。

    trace 体积很小（数十 KB 量级），随报告内联后“查看详情”里的关键截图与
    五维明细无需后端接口即可展示。
    """
    traces: dict[str, dict] = {}
    for sr in report_data.get("sample_results", []):
        sample_id = sr.get("sample_id", "")
        platform = sr.get("platform", "")
        if not sample_id or not platform:
            continue
        if traces.get(sample_id, {}).get(platform) is not None:
            continue
        trace = _load_json(workspace_dir / sample_id / f"aesthetics_trace_{platform}.json")
        if trace:
            traces.setdefault(sample_id, {})[platform] = trace
    return traces


def _load_command_history(workspace_dir: Path) -> list[dict]:
    """读取工作区指令历史，供报告页“操作历史”展示。"""
    data = _load_json(workspace_dir / "command_history.json")
    if isinstance(data, dict):
        commands = data.get("commands")
    else:
        commands = data
    return commands if isinstance(commands, list) else []


def _migrate_report_paths(report_data_dict: dict, workspace_dir: Path) -> None:
    """迁移旧的绝对路径 report_path 为工作区相对路径。"""
    from .e2e_paths import migrate_e2e_report_paths

    migrate_e2e_report_paths(report_data_dict, workspace_dir)
