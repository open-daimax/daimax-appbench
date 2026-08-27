"""E2E 报告路径解析：把绝对路径 report_path 改写为工作区根目录相对路径。

report.html 位于工作区根目录，本地报告直接以相对路径打开 e2e 报告文件；
Web 控制台的 /e2e-report/{path} 端点也按同一语义解析（见
studio/backend/evalstudio/workspace/report_loader.py:resolve_e2e_report_file）。

工作区存在两种 e2e 报告布局，导出目录名的构成不同：

* 工作区级 ``e2e_reports/{sample}_{platform}_{tc}_{timestamp}/``
* 样本级   ``{sample}/e2e_reports/{platform}_{tc}_{timestamp}/`` — 目录名不含
  样本前缀，建索引时必须补上，否则与查询键 ``{sample}_{platform}_{tc}``
  不同构，样本级布局下的用例永远匹配不到报告文件。
"""

from __future__ import annotations

from pathlib import Path

_STALE_PREFIX = "STALE_"

# 索引项：(条目路径, 条目父目录相对工作区根的路径)
_IndexEntry = tuple[Path, str]


def _dir_prefix(name: str) -> str:
    """去掉 STALE_ 前缀与结尾的 {YYYYMMDD_HHMMSS} 时间戳，得到匹配用前缀。"""
    clean = name[len(_STALE_PREFIX):] if name.startswith(_STALE_PREFIX) else name
    parts = clean.rsplit("_", 2)
    return "_".join(parts[:-2]) if len(parts) >= 3 else name


def build_export_index(workspace: Path) -> dict[str, list[_IndexEntry]]:
    """建立 ``{sample}_{platform}_{tc}`` -> 候选导出条目 的索引。"""
    from ..store import _sanitise_name

    index: dict[str, list[_IndexEntry]] = {}

    ws_e2e_dir = workspace / "e2e_reports"
    if ws_e2e_dir.is_dir():
        for entry in ws_e2e_dir.iterdir():
            index.setdefault(_dir_prefix(entry.name), []).append((entry, "e2e_reports"))

    for sample_dir in workspace.iterdir():
        if not sample_dir.is_dir():
            continue
        sample_e2e_dir = sample_dir / "e2e_reports"
        if not sample_e2e_dir.is_dir():
            continue
        item_token = _sanitise_name(sample_dir.name, "item")
        rel_parent = f"{sample_dir.name}/e2e_reports"
        for entry in sample_e2e_dir.iterdir():
            key = f"{item_token}_{_dir_prefix(entry.name)}"
            index.setdefault(key, []).append((entry, rel_parent))

    return index


def _resolve_html(entries: list[_IndexEntry]) -> str | None:
    """在候选条目中取最新的一个 HTML 报告，返回工作区根相对路径。"""
    for entry, rel_parent in sorted(entries, key=lambda item: item[0].name, reverse=True):
        if entry.is_dir():
            html = entry / "report.html"
            if not html.exists():
                candidates = sorted(entry.glob("*.html"))
                if not candidates:
                    continue
                html = candidates[0]
            return f"{rel_parent}/{entry.name}/{html.name}"
        if entry.is_file() and entry.suffix == ".html":
            return f"{rel_parent}/{entry.name}"
    return None


def find_case_report(
    index: dict[str, list[_IndexEntry]],
    sample_id: str,
    platform: str,
    tc_id: str,
) -> str | None:
    """查找某个用例的 e2e 报告 HTML，返回工作区根相对路径。"""
    from ..store import _sanitise_name

    key = (
        f"{_sanitise_name(sample_id, 'item')}"
        f"_{_sanitise_name(platform, 'unknown')}"
        f"_{_sanitise_name(tc_id, 'tc')}"
    )
    entries = index.get(key) or index.get(f"{_STALE_PREFIX}{key}")
    return _resolve_html(entries) if entries else None


def migrate_e2e_report_paths(report_data: dict, workspace: Path) -> None:
    """把 e2e_test_cases 中的绝对路径 report_path 改写为工作区相对路径。

    绝对路径指向评测机的本地缓存目录，报告导出后无法访问；已是相对路径的
    条目不动。匹配不到导出文件时保留原值，由报告页按“绝对路径不可访问”降级。
    """
    index = build_export_index(workspace)
    if not index:
        return

    for sr in report_data.get("sample_results", []):
        sample_id = sr.get("sample_id", "")
        platform = sr.get("platform", "")
        for case in sr.get("e2e_test_cases", []):
            report_path = case.get("report_path", "")
            if not report_path or not report_path.startswith("/"):
                continue
            resolved = find_case_report(index, sample_id, platform, case.get("test_case_id", ""))
            if resolved:
                case["report_path"] = resolved
