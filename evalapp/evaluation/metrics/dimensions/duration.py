"""耗时维度：分段线性递减评分与跨样本耗时统计。

（V2 doc "生成成本 > 阶段耗时"）
Scoring: shorter is better.  Each phase maps duration to 0-100 using
configurable *excellent* and *poor* thresholds (milliseconds).
Below excellent → 100, above poor → 0, linear in between.
"""

from __future__ import annotations

import math
from functools import lru_cache
from typing import TYPE_CHECKING, Sequence

from ..models import (
    DurationScore,
    DurationStatistics,
    PhaseDurationScore,
    PhaseStatistics,
)
from ..rules import (
    DURATION_DEFAULT_THRESHOLDS,
    DURATION_DEFAULT_TIMEOUT_MS,
    DURATION_MID_SCORE,
    DURATION_MID_THRESHOLD_MS,
)

if TYPE_CHECKING:
    # 仅供类型注解；运行时延迟导入以避免 metrics ↔ results 循环导入
    from ...results.models import DurationMetrics


def _score_phase_duration(
    duration_ms: int | None,
    excellent_ms: int,
    poor_ms: int,
) -> float:
    """Score a single phase duration on a 0-100 scale.

    [性能优化] 代理到缓存版本，纯函数可复用计算结果。
    """
    if duration_ms is None:
        return 0.0
    return _score_phase_duration_cached(int(duration_ms), int(excellent_ms), int(poor_ms))


@lru_cache(maxsize=2048)
def _score_phase_duration_cached(
    duration_ms: int,
    excellent_ms: int,
    poor_ms: int,
) -> float:
    """Cached scoring kernel for phase duration.

    采用分段线性递减策略：
    - ≤ excellent_ms: 100分
    - excellent_ms ~ 30分钟: 从100分线性递减到5分
    - 30分钟 ~ poor_ms: 从5分线性递减到0分
    - ≥ poor_ms: 0分
    """
    mid_threshold_ms = DURATION_MID_THRESHOLD_MS
    mid_score = DURATION_MID_SCORE

    if duration_ms <= excellent_ms:
        return 100.0

    if duration_ms >= poor_ms:
        return 0.0

    # 分段线性插值
    if duration_ms <= mid_threshold_ms:
        # 2分钟~30分钟：从100分递减到5分
        return round(
            100.0 - (100.0 - mid_score) * (duration_ms - excellent_ms) / (mid_threshold_ms - excellent_ms), 1
        )
    else:
        # 30分钟~60分钟：从5分递减到0分
        return round(
            mid_score * (poor_ms - duration_ms) / (poor_ms - mid_threshold_ms), 1
        )


def score_duration(
    durations: "DurationMetrics",
    thresholds: dict[str, tuple[int, int]] | None = None,
    timeout_ms: int | None = None,
) -> DurationScore:
    """Compute per-sample duration score from collected durations.

    Based on end-to-end total duration for linear scoring.

    Args:
        durations: DurationMetrics from process collection.
        thresholds: Optional per-phase (excellent_ms, poor_ms) overrides.
        timeout_ms: Total duration timeout threshold in ms.

    Returns:
        DurationScore with total score (composite_score = total.score).
    """

    th = {**DURATION_DEFAULT_THRESHOLDS, **(thresholds or {})}
    t_timeout = timeout_ms or DURATION_DEFAULT_TIMEOUT_MS

    total = PhaseDurationScore(
        duration_ms=durations.total_ms,
        score=_score_phase_duration(durations.total_ms, *th["total"]),
    )

    is_timeout = (
        durations.total_ms is not None and durations.total_ms > t_timeout
    )

    return DurationScore(
        total=total,
        composite_score=round(total.score, 1),
        is_timeout=is_timeout,
    )


def compute_duration_statistics(
    duration_scores: Sequence[DurationScore],
    durations_list: Sequence["DurationMetrics"],
) -> DurationStatistics:
    """Compute aggregate duration statistics across multiple samples.

    Args:
        duration_scores: Per-sample DurationScore objects.
        durations_list: Per-sample DurationMetrics (raw ms values).

    Returns:
        DurationStatistics with total mean/median/P90/P95 and timeout rate.
    """
    n = len(durations_list)
    if n == 0:
        return DurationStatistics()

    def _phase_stats(values: list[int]) -> PhaseStatistics:
        if not values:
            return PhaseStatistics()
        sv = sorted(values)
        count = len(sv)
        return PhaseStatistics(
            count=count,
            mean_ms=round(sum(sv) / count, 1),
            median_ms=float(_percentile(sv, 50)),
            p90_ms=float(_percentile(sv, 90)),
            p95_ms=float(_percentile(sv, 95)),
            min_ms=float(sv[0]),
            max_ms=float(sv[-1]),
        )

    total_vals = [d.total_ms for d in durations_list if d.total_ms is not None]

    timeout_count = sum(1 for ds in duration_scores if ds.is_timeout)
    scores = [ds.composite_score for ds in duration_scores]
    mean_score = round(sum(scores) / len(scores), 1) if scores else 0.0

    return DurationStatistics(
        total_samples=n,
        total=_phase_stats(total_vals),
        timeout_count=timeout_count,
        timeout_rate=round(timeout_count / n, 4) if n > 0 else 0.0,
        mean_score=mean_score,
    )


def _percentile(sorted_values: list[int], pct: int) -> float:
    """Compute the *pct*-th percentile of a sorted list using linear interpolation."""
    n = len(sorted_values)
    if n == 0:
        return 0.0
    if n == 1:
        return float(sorted_values[0])
    k = (pct / 100) * (n - 1)
    f = math.floor(k)
    c = min(f + 1, n - 1)
    d = k - f
    return sorted_values[f] + d * (sorted_values[c] - sorted_values[f])
