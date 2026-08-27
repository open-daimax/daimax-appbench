"""包大小维度：基于构建产物大小的分档线性插值评分与展示格式化。"""

from __future__ import annotations

from functools import lru_cache

from ..rules import (
    PACKAGE_SIZE_EXCELLENT_SCORE,
    PACKAGE_SIZE_FAIR_SCORE,
    PACKAGE_SIZE_FLOOR_SCORE,
    PACKAGE_SIZE_GOOD_SCORE,
    PACKAGE_SIZE_THRESHOLDS,
)


def score_package_size(size_bytes: int) -> float:
    """基于构建产物大小计算评分(0-100)

    [性能优化] 纯函数，使用 ``lru_cache`` 缓存重复计算。

    评分规则(对移动应用):
    - ≤10MB: 100分(优秀，极轻量)
    - ≤30MB: 80分(良好)
    - ≤60MB: 60分(一般)
    - ≤100MB: 40分(较大)
    - >100MB: 20分(过大)

    区间内使用线性插值平滑过渡
    """
    return _score_package_size_cached(int(size_bytes))


@lru_cache(maxsize=1024)
def _score_package_size_cached(size_bytes: int) -> float:
    if size_bytes <= 0:
        return 0.0

    # 阈值区间见 rules.PACKAGE_SIZE_THRESHOLDS
    # 在区间内随 ratio (0→1) 线性递减： score = upper_score - score_range * ratio
    prev_threshold = 0
    for threshold, upper_score, score_range in PACKAGE_SIZE_THRESHOLDS:
        if size_bytes <= threshold:
            ratio = (size_bytes - prev_threshold) / (threshold - prev_threshold)
            # 修复 off-by-one: 原公式 `base_score + score_range * (1.0 - ratio)`
            # 会令 0MB 输出 120、5MB 输出 110，超出注释标称区间。
            # 边界值验证: 0MB=100, 5MB=90, 10MB=80, 20MB=70, 30MB=60,
            #            45MB=50, 60MB=40, 80MB=30, 100MB=20, >100MB=20
            return round(upper_score - score_range * ratio, 1)
        prev_threshold = threshold

    # 超过100MB
    return PACKAGE_SIZE_FLOOR_SCORE


def generate_package_size_reason(size_bytes: int, score: float) -> str:
    """生成包大小原因说明"""
    if size_bytes <= 0:
        return ""

    size_display = format_size_display(size_bytes)
    if score >= PACKAGE_SIZE_EXCELLENT_SCORE:
        return f"包体积优秀（{size_display}），有利于下载转化"
    elif score >= PACKAGE_SIZE_GOOD_SCORE:
        return f"包体积良好（{size_display}）"
    elif score >= PACKAGE_SIZE_FAIR_SCORE:
        return f"包体积一般（{size_display}），可能影响下载转化"
    else:
        return f"包体积较大（{size_display}），显著影响下载转化"


def format_size_display(size_bytes: int) -> str:
    """格式化文件大小为人类可读格式。

    [性能优化] 纯函数，使用 ``lru_cache`` 避免重复格式化。
    """
    return _format_size_display_cached(int(size_bytes))


@lru_cache(maxsize=1024)
def _format_size_display_cached(size_bytes: int) -> str:
    """实际格式化逻辑（被缓存包裹）。"""
    if size_bytes < 1024:
        return f"{size_bytes}B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f}KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f}MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f}GB"
