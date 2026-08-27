"""稳定性维度：基于 crash/ANR/白屏 次数计算稳定性得分。"""

from __future__ import annotations

from ..models import StabilityMetrics


def score_stability(metrics: StabilityMetrics) -> float | None:
    """Compute a 0-100 stability score.

    Formula: score = max(0, (1 - issue_rate)) × 100
    Where: issue_rate = (crash_count + anr_count + white_screen_count) / total_test_runs

    The score directly represents the percentage of clean (issue-free) test runs.
    When issue_rate >= 1.0 (issues exceed total runs), score clamps to 0.

    Returns:
        float: 0-100 score if data is available
        None: if no test data available (cannot assess stability)
    """
    if metrics.total_test_runs == 0:
        return None

    issue_count = metrics.crash_count + metrics.anr_count + metrics.white_screen_count
    issue_rate = issue_count / metrics.total_test_runs
    return max(0.0, (1.0 - issue_rate)) * 100.0
