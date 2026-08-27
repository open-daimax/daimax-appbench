"""功能维度：核心功能覆盖与状态处理完整性评分。"""

from __future__ import annotations

from ..models import CoreFunctionCoverage, StateHandlingMetrics
from ..rules import FUNCTIONALITY_FAILED_PENALTY

# Scoring bands (V2 doc section 3.2):
#   90-100  All core functions present, main tasks completable
#   75-89   Minor non-core gaps
#   50-74   Some core functions missing or broken
#   0-49    Core functions unusable


def score_core_function_coverage(metrics: CoreFunctionCoverage) -> float:
    """Compute a 0-100 core function coverage score."""
    if metrics.total_functions == 0:
        # No baseline functions defined — score as N/A → 0
        return 0.0

    rate = metrics.coverage_rate

    # Check how many functions failed (present but broken)
    failed_count = sum(
        1 for v in metrics.function_results.values() if v == "failed"
    )
    failed_rate = failed_count / metrics.total_functions

    # Base score from coverage rate (linear mapping)
    base_score = rate * 100.0

    # Penalty for failed functions (worse than missing — they exist but are broken)
    penalty = failed_rate * FUNCTIONALITY_FAILED_PENALTY

    return max(0.0, min(100.0, base_score - penalty))


# State handling scoring bands (V2 doc section 3.2):
#   90-100  All states handled
#   75-89   Most states handled
#   50-74   Some states handled
#   0-49    States largely unhandled


def score_state_handling(metrics: StateHandlingMetrics) -> float:
    """Compute a 0-100 state handling completeness score."""
    if metrics.total_states == 0:
        return 0.0

    rate = metrics.completeness_rate

    # Direct linear mapping — the rate itself is already a good score proxy
    # because the 4 state types are each equally weighted.
    return round(rate * 100.0, 1)
