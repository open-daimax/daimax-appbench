"""后端完整性维度：基于 real_backend 验证结果计算后端完整性得分与原因。"""

from __future__ import annotations

from ..rules import (
    BACKEND_PASS_RATE_FULL,
    BACKEND_PASS_RATE_MOSTLY,
    BACKEND_PASS_RATE_PARTIAL,
)


def score_backend_completeness(
    requires_backend: bool,
    real_backend_pass: bool | None = None,
    real_backend_pass_rate: float | None = None,
) -> tuple[float | None, str]:
    """计算后端完整性得分（按通过率计分）并生成原因说明。

    Args:
        requires_backend: 样本是否需要后端服务
        real_backend_pass: 后端验证是否通过, None表示无real_backend数据
        real_backend_pass_rate: 后端验证通过率 (0.0-1.0), None表示无数据

    Returns:
        (得分 0-100 或 None, 原因说明)；不需要后端的样本返回 (None, 不参与评分说明)。
    """
    if not requires_backend:
        return None, "该样本不需要后端服务，不参与评分"

    if real_backend_pass_rate is not None and real_backend_pass_rate > 0:
        score = real_backend_pass_rate * 100.0
        if real_backend_pass_rate >= BACKEND_PASS_RATE_FULL:
            reason = "后端服务验证全部通过"
        elif real_backend_pass_rate >= BACKEND_PASS_RATE_MOSTLY:
            reason = f"后端服务大部分验证通过（通过率{real_backend_pass_rate*100:.0f}%）"
        elif real_backend_pass_rate >= BACKEND_PASS_RATE_PARTIAL:
            reason = f"后端服务部分验证通过（通过率{real_backend_pass_rate*100:.0f}%）"
        else:
            reason = f"后端服务验证大部分未通过（通过率{real_backend_pass_rate*100:.0f}%）"
        return score, reason

    if real_backend_pass is False:
        return 0.0, "后端服务验证未通过"

    # real_backend_pass 为 None, 表示无 real_backend 数据
    return 0.0, "后端服务验证数据缺失"
