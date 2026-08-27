"""代码质量维度：静态扫描 / 圈复杂度 / 重复代码率 三个子指标加权评分。"""

from __future__ import annotations

from ..models import CodeQualityMetrics
from ..rules import (
    CODE_QUALITY_COMPLEXITY_WEIGHT,
    CODE_QUALITY_COMPLIANCE_BONUS_MAX,
    CODE_QUALITY_DUPLICATION_WEIGHT,
    CODE_QUALITY_ERROR_PENALTY,
    CODE_QUALITY_HIGH_COMPLEXITY_PENALTY,
    CODE_QUALITY_NEUTRAL_SCORE,
    CODE_QUALITY_STATIC_SCAN_WEIGHT,
    CODE_QUALITY_WARNING_PENALTY,
)

# Scoring bands (V2 doc section 3.3):
#   90-100  Few warnings, clear structure, manageable complexity
#   75-89   Minor convention or structure issues
#   50-74   Notable quality issues but maintainable
#   0-49    Chaotic code, high risk


def score_code_quality(metrics: CodeQualityMetrics) -> float:
    """Compute a 0-100 code quality score (rule-based portion).

    Weights:
      - Static scan / convention compliance: 40%
      - Cyclomatic complexity: 30%
      - Duplicate code ratio: 30%
    """
    scan_score = _score_static_scan(metrics)
    complexity_score = _score_complexity(metrics)
    duplication_score = _score_duplication(metrics)

    composite = (
        scan_score * CODE_QUALITY_STATIC_SCAN_WEIGHT
        + complexity_score * CODE_QUALITY_COMPLEXITY_WEIGHT
        + duplication_score * CODE_QUALITY_DUPLICATION_WEIGHT
    )
    return round(max(0.0, min(100.0, composite)), 1)


def _score_static_scan(metrics: CodeQualityMetrics) -> float:
    """Score based on static scan issue counts and compliance rate.

    Uses a penalty model driven primarily by error count, then warning count.
    A project with zero issues gets 100.
    """
    # If no scan tools ran successfully, return 0 (cannot assess)
    if not any(sr.success for sr in metrics.scan_results):
        return 0.0

    errors = metrics.error_count
    warnings = metrics.warning_count

    if errors == 0 and warnings == 0:
        return 100.0

    # Penalty: each error costs 5 points, each warning costs 1 point
    penalty = errors * CODE_QUALITY_ERROR_PENALTY + warnings * CODE_QUALITY_WARNING_PENALTY

    # Also factor in the compliance rate (higher is better)
    compliance_bonus = metrics.convention_compliance_rate * CODE_QUALITY_COMPLIANCE_BONUS_MAX

    score = 100.0 - penalty + compliance_bonus
    return max(0.0, min(100.0, score))


def _score_complexity(metrics: CodeQualityMetrics) -> float:
    """Score based on cyclomatic complexity analysis.

    Average CC ≤ 5 is excellent, 5-10 good, 10-15 moderate, >15 high risk.
    """
    cr = metrics.complexity_result
    if not cr.success or cr.total_functions == 0:
        # No data — assume neutral
        return CODE_QUALITY_NEUTRAL_SCORE

    avg = cr.avg_complexity
    high_ratio = metrics.high_complexity_ratio

    # Base score from average complexity
    if avg <= 5.0:
        base = 100.0
    elif avg <= 10.0:
        base = 100.0 - (avg - 5.0) * 4.0  # 100 → 80
    elif avg <= 15.0:
        base = 80.0 - (avg - 10.0) * 4.0  # 80 → 60
    else:
        base = max(20.0, 60.0 - (avg - 15.0) * 4.0)

    # Penalty for high-complexity functions
    ratio_penalty = high_ratio * CODE_QUALITY_HIGH_COMPLEXITY_PENALTY

    return max(0.0, min(100.0, base - ratio_penalty))


def _score_duplication(metrics: CodeQualityMetrics) -> float:
    """Score based on duplicate code ratio.

    Duplication rate thresholds:
    - ≤ 3%: excellent (95-100)
    - 3-5%: good (80-95)
    - 5-10%: moderate (60-80)
    - 10-20%: concerning (40-60)
    - > 20%: high risk (0-40)
    """
    dr = metrics.duplication_result
    if not dr.success:
        # No data — assume neutral
        return CODE_QUALITY_NEUTRAL_SCORE

    rate = dr.duplication_rate

    if rate <= 0.03:
        return 100.0 - rate * 166.7  # 100 → 95
    if rate <= 0.05:
        return 95.0 - (rate - 0.03) * 750.0  # 95 → 80
    if rate <= 0.10:
        return 80.0 - (rate - 0.05) * 400.0  # 80 → 60
    if rate <= 0.20:
        return 60.0 - (rate - 0.10) * 200.0  # 60 → 40
    return max(0.0, 40.0 - (rate - 0.20) * 200.0)
