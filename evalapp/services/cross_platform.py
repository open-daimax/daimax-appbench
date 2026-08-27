"""跨平台一致性对比计算。

当工作区包含同一 sample_id 在多个平台的评测结果时，生成跨平台一致性对比数据，
写入 report_data 的 cross_platform_comparison 顶层字段。

一致性分算法：
    一致性分 = 100 - (各平台评分标准差的均值 * 系数)
    标准差 0 → 100 分，标准差 50 → 0 分。
"""

from __future__ import annotations

import statistics
from pathlib import Path

from ..utils.logging import get_logger

logger = get_logger(__name__)

# 参与一致性计算的维度（与 sample_results 中的 *_score 字段对应）
_COMPARISON_DIMENSIONS = [
    ("success_rate", "success_rate_score"),
    ("quality", "quality_score"),
    ("experience", "experience_score"),
]


def calculate_consistency_score(platform_scores: dict[str, dict]) -> float:
    """计算多平台一致性分。

    一致性分 = 100 - (各维度标准差的均值 * 系数)

    Args:
        platform_scores: 各平台评分，格式如
            ``{"expo_ios": {"success_rate": 100, "quality": 72, "experience": 80},
               "expo_android": {"success_rate": 100, "quality": 68, "experience": 75}}``

    Returns:
        一致性分（0 ~ 100），单平台或无可比维度时返回 100.0
    """
    dim_names = [dim for dim, _ in _COMPARISON_DIMENSIONS]
    std_devs: list[float] = []

    for dim in dim_names:
        values = [
            scores[dim]
            for scores in platform_scores.values()
            if scores.get(dim) is not None
        ]
        if len(values) >= 2:
            std_devs.append(statistics.stdev(values))

    if not std_devs:
        return 100.0

    avg_std = sum(std_devs) / len(std_devs)
    # 标准差 0 → 100 分，标准差 50 → 0 分
    score = max(0.0, 100.0 - avg_std * 2)
    return round(score, 1)


def build_cross_platform_comparison(
    report_data: dict,
    workspace_dir: Path | None = None,
) -> dict:
    """从 report_data 中的 sample_results 构建跨平台对比数据。

    仅当同一 sample_id 在 2 个及以上平台有结果时才生成对比条目。

    Args:
        report_data: 内存中的 report_data 字典
        workspace_dir: 工作区路径（用于检测多平台模式）

    Returns:
        ``{sample_id: {platforms, consistency_score, dimension_comparison, screenshots}}``
        无跨平台数据时返回空字典 ``{}``
    """
    sample_results = report_data.get("sample_results", [])
    if not sample_results:
        return {}

    # 按 sample_id 分组
    samples_by_id: dict[str, list[dict]] = {}
    for sr in sample_results:
        sid = sr.get("sample_id", "")
        if not sid:
            continue
        samples_by_id.setdefault(sid, []).append(sr)

    comparison: dict = {}

    for sample_id, entries in sorted(samples_by_id.items()):
        # 收集唯一平台
        seen_platforms: dict[str, dict] = {}
        for sr in entries:
            plat = sr.get("platform", "")
            if plat and plat not in seen_platforms:
                seen_platforms[plat] = sr

        platforms = list(seen_platforms.keys())
        if len(platforms) < 2:
            continue

        # 构建各平台评分
        platform_scores: dict[str, dict] = {}
        for plat, sr in seen_platforms.items():
            platform_scores[plat] = {
                dim: sr.get(score_key, 0)
                for dim, score_key in _COMPARISON_DIMENSIONS
            }

        # 计算一致性分
        consistency_score = calculate_consistency_score(platform_scores)

        # 构建维度对比
        dimension_comparison: dict[str, dict[str, float]] = {}
        for dim, score_key in _COMPARISON_DIMENSIONS:
            dimension_comparison[dim] = {
                plat: platform_scores[plat][dim]
                for plat in platforms
            }

        # e2e_pass_rate 对比
        e2e_comparison: dict[str, float] = {}
        for plat, sr in seen_platforms.items():
            cases = sr.get("e2e_test_cases", [])
            if cases and isinstance(cases, list):
                passed = sum(
                    1 for c in cases
                    if isinstance(c, dict) and (c.get("status") == "PASS" or c.get("passed"))
                )
                total = len(cases)
                e2e_comparison[plat] = round(passed / total, 2) if total > 0 else 0.0
            else:
                e2e_comparison[plat] = 0.0
        dimension_comparison["e2e_pass_rate"] = e2e_comparison

        # screenshots 路径
        screenshots: dict[str, str] = {}
        for plat, sr in seen_platforms.items():
            # 优先从 e2e_test_cases 的 TC_LAUNCH 找 report_path
            screenshot_path = _find_launch_screenshot(sr)
            if not screenshot_path:
                # 回退到命名约定
                screenshot_path = f"{sample_id}/screenshots/launch_{plat}.jpg"
            screenshots[plat] = screenshot_path

        comparison[sample_id] = {
            "platforms": sorted(platforms),
            "consistency_score": consistency_score,
            "dimension_comparison": dimension_comparison,
            "screenshots": screenshots,
        }

    return comparison


def _find_launch_screenshot(sr: dict) -> str:
    """从 sample_result 的 e2e_test_cases 中提取 TC_LAUNCH 的 report_path。"""
    for tc in sr.get("e2e_test_cases", []):
        if not isinstance(tc, dict):
            continue
        if tc.get("test_case_id") == "TC_LAUNCH" and tc.get("report_path"):
            return tc["report_path"]
    return ""


def enrich_report_data_with_cross_platform(
    report_data: dict,
    workspace_dir: Path | None = None,
) -> None:
    """就地修改 report_data，添加跨平台一致性对比数据。

    **改动 A**：``meta.platform`` 多平台时改为数组格式
    **改动 B**：新增 ``cross_platform_comparison`` 顶层字段
    **改动 C**：``top_level_summary`` 新增 ``mean_consistency_score``

    向后兼容：
    - 单平台工作区不生成 cross_platform_comparison 条目（字段为空对象 ``{}``）
    - ``meta.platform`` 单平台保持字符串
    """
    from ..workspace.paths import load_workspace_platforms

    # --- 改动 A: meta.platform 支持数组格式 ---
    meta = report_data.get("meta", {})
    if workspace_dir is not None:
        workspace_dir = Path(workspace_dir)
        platforms_list = load_workspace_platforms(workspace_dir)
        if len(platforms_list) > 1:
            # 多平台时使用数组格式
            meta["platform"] = platforms_list
        elif len(platforms_list) == 1:
            # 单平台保持字符串（向后兼容）
            meta["platform"] = platforms_list[0]

    # --- 改动 B: 新增 cross_platform_comparison ---
    comparison = build_cross_platform_comparison(report_data, workspace_dir)
    report_data["cross_platform_comparison"] = comparison

    # --- 改动 C: top_level_summary 新增 mean_consistency_score ---
    if comparison:
        scores = [v["consistency_score"] for v in comparison.values()]
        mean_score = round(sum(scores) / len(scores), 1)
    else:
        # 单平台无一致性分
        mean_score = None

    top_level = report_data.setdefault("top_level_summary", {})
    top_level["mean_consistency_score"] = mean_score

    if comparison:
        logger.info(
            "跨平台对比: %d 个样本有跨平台数据, 平均一致性分=%.1f",
            len(comparison),
            mean_score if mean_score is not None else 0,
        )
