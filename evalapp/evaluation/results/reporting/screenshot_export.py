"""把 e2e 报告 HTML 内嵌的用例步骤截图解码落盘，供本地报告按用例展示。

Web 控制台是在请求时从 e2e 报告 HTML 里解码 base64 截图返回的；本地报告没有
后端，也无法把全量截图内联进单文件（实测 33 样本约 1GB）。因此在生成报告时
按用例限量落盘到 ``{sample}/screenshots/``，文件名遵循
``{platform}_{tc_id}_step_{n}`` 约定，报告页的截图条即可按 tc_id 索引到。

限量策略：每个用例均匀抽取 MAX_SHOTS_PER_CASE 帧（含首帧与末帧），保留原始
step 序号，因此文件名不连续但顺序与执行过程一致。
"""

from __future__ import annotations

import base64
import re
from pathlib import Path

from ....utils.logging import get_logger
from ..comparison.screenshot_extractor import extract_all_screenshots
from .e2e_paths import build_export_index, find_case_report

logger = get_logger(__name__)

# 每个用例落盘的最大截图数（单帧约 10KB，全量落盘会让工作区膨胀近 1GB）
MAX_SHOTS_PER_CASE = 8

_DATA_URL_RE = re.compile(r"^data:image/(?P<fmt>[a-zA-Z0-9.+-]+);base64,(?P<body>.+)$", re.S)
_STEP_NAME_RE = re.compile(r"(\d+)")

_EXT_BY_FORMAT = {"jpeg": ".jpg", "jpg": ".jpg", "png": ".png", "webp": ".webp"}


def _decode_data_url(url: str) -> tuple[bytes, str] | None:
    """解析 data URL，返回 (图片字节, 扩展名)。"""
    if not isinstance(url, str):
        return None
    m = _DATA_URL_RE.match(url.strip())
    if not m:
        return None
    try:
        blob = base64.b64decode(m.group("body"), validate=False)
    except (ValueError, TypeError):
        return None
    if not blob:
        return None
    return blob, _EXT_BY_FORMAT.get(m.group("fmt").lower(), ".jpg")


def _step_index(shot: dict, fallback: int) -> int:
    """从 step_name（形如 step_12）取步骤序号，取不到时用序位兜底。"""
    m = _STEP_NAME_RE.search(str(shot.get("step_name") or ""))
    return int(m.group(1)) if m else fallback


def _pick_evenly(shots: list[dict], limit: int) -> list[dict]:
    """均匀抽取至多 limit 帧，必定包含首帧与末帧。"""
    if limit <= 0 or len(shots) <= limit:
        return shots
    if limit == 1:
        return [shots[0]]
    last = len(shots) - 1
    picked_idx = sorted({round(i * last / (limit - 1)) for i in range(limit)})
    return [shots[i] for i in picked_idx]


def _export_case(
    html_path: Path,
    out_dir: Path,
    platform: str,
    tc_id: str,
    limit: int,
) -> int:
    prefix = f"{platform}_{tc_id}_step_"
    # 已导出过则跳过：重复生成报告时无需再解码 MB 级 HTML
    if out_dir.is_dir() and any(out_dir.glob(f"{prefix}*")):
        return 0
    if not html_path.is_file():
        return 0

    try:
        shots = extract_all_screenshots(html_path)
    except Exception as e:  # 单个报告解析失败不影响其余用例
        logger.debug("解析 e2e 报告截图失败 (%s): %s", html_path, e)
        return 0
    if not shots:
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for pos, shot in enumerate(_pick_evenly(shots, limit), start=1):
        decoded = _decode_data_url(shot.get("url", ""))
        if decoded is None:
            continue
        blob, ext = decoded
        target = out_dir / f"{prefix}{_step_index(shot, pos)}{ext}"
        try:
            target.write_bytes(blob)
        except OSError as e:
            logger.debug("写入用例截图失败 (%s): %s", target, e)
            continue
        written += 1
    return written


def export_case_screenshots(
    workspace_dir: Path,
    report_data: dict,
    *,
    max_per_case: int = MAX_SHOTS_PER_CASE,
) -> int:
    """为报告数据中的每个用例落盘步骤截图，返回新写入的文件数。"""
    index = build_export_index(workspace_dir)
    if not index:
        return 0

    total = 0
    for sr in report_data.get("sample_results", []):
        sample_id = sr.get("sample_id", "")
        platform = sr.get("platform", "")
        if not sample_id or not platform:
            continue
        out_dir = workspace_dir / sample_id / "screenshots"
        for case in sr.get("e2e_test_cases", []):
            tc_id = case.get("test_case_id", "")
            if not tc_id:
                continue
            rel_html = find_case_report(index, sample_id, platform, tc_id)
            if not rel_html:
                continue
            total += _export_case(
                workspace_dir / rel_html, out_dir, platform, tc_id, max_per_case,
            )

    if total:
        logger.info("已导出用例步骤截图 %d 张（每用例上限 %d）", total, max_per_case)
    return total
