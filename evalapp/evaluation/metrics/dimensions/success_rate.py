"""成功率维度：首次生成 + 问题修复（预留）+ 补充需求（预留）加权平均。"""

from __future__ import annotations

from ..models import SuccessRateMetrics


def compute_success_rate(
    initial_rate: float,
    issue_fix_rate: float = 0.0,
    requirement_extension_rate: float = 0.0,
    gen_ok: bool = False,
    launch_ok: bool = False,
) -> SuccessRateMetrics:
    """计算综合成功率 - 三个子维度加权平均

    Args:
        initial_rate: 首次生成成功率 (0-1或0-100)
        issue_fix_rate: 问题修复成功率 (预留)
        requirement_extension_rate: 补充需求成功率 (预留)
        gen_ok: 应用是否生成成功
        launch_ok: 应用是否启动成功

    Returns:
        SuccessRateMetrics with composite_score
    """
    # 归一化到0-100
    initial_rate_100 = initial_rate * 100 if initial_rate <= 1.0 else initial_rate
    issue_fix_rate_100 = issue_fix_rate * 100 if issue_fix_rate <= 1.0 else issue_fix_rate
    req_ext_rate_100 = requirement_extension_rate * 100 if requirement_extension_rate <= 1.0 else requirement_extension_rate

    # 生成首次生成成功率的原因说明
    if gen_ok and launch_ok:
        initial_reason = "应用生成成功且可正常启动"
    elif not gen_ok:
        initial_reason = "应用生成失败，未能产出可运行代码"
    elif gen_ok and not launch_ok:
        initial_reason = "应用生成成功但启动失败，存在崩溃或白屏"
    else:
        initial_reason = ""

    metrics = SuccessRateMetrics(
        initial_generation_rate=initial_rate_100,
        issue_fix_rate=issue_fix_rate_100,
        requirement_extension_rate=req_ext_rate_100,
        initial_generation_reason=initial_reason,
        issue_fix_reason="该功能暂未接入，后续支持多轮对话修复问题后的成功率评估",
        requirement_extension_reason="该功能暂未接入，后续支持用户补充需求后的成功率评估",
    )

    # 动态权重归一化：未实现的指标项不计入权重
    # initial_generation_rate 始终视为已实现（核心指标）
    # issue_fix_rate / requirement_extension_rate 仅在有值时参与计算
    active_items = [(initial_rate_100, metrics.initial_generation_weight)]

    if issue_fix_rate_100 is not None and issue_fix_rate_100 > 0:
        active_items.append((issue_fix_rate_100, metrics.issue_fix_weight))

    if req_ext_rate_100 is not None and req_ext_rate_100 > 0:
        active_items.append((req_ext_rate_100, metrics.requirement_extension_weight))

    total_weight = sum(w for _, w in active_items)
    if total_weight > 0:
        metrics.composite_score = sum(v * w for v, w in active_items) / total_weight
    else:
        metrics.composite_score = 0.0

    return metrics
