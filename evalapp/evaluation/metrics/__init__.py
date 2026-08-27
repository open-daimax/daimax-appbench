"""Evaluation metrics package — public facade for scoring dimension processors, rules, and data collectors.

Top-level metrics:
- Success Rate: initial generation + issue fix + requirement extension
- Quality: functionality completeness + stability + backend completeness
- Experience: end-to-end duration + package size + UI aesthetics (token usage shown only)

Package structure:
- rules.py:     All scoring rule constants (weights/thresholds/deduction factors) — single source of truth
- dimensions/:  Scoring dimension processors (pure scoring logic + reason text generation)
- collectors/:  Raw data collectors (run tools/parse logs/invoke AI)
- models.py:    Cross-dimension shared Pydantic data models

External code should uniformly import scoring functions and models from this facade.
"""

from .dimensions import (
    compute_duration_statistics,
    compute_experience,
    compute_quality,
    compute_success_rate,
    score_backend_completeness,
    score_code_quality,
    score_core_function_coverage,
    score_duration,
    score_package_size,
    score_stability,
    score_state_handling,
)
from .models import (
    ANREvent,
    CodeQualityMetrics,
    ComplexityResult,
    CoreFunctionCoverage,
    CrashEvent,
    DuplicationResult,
    DurationScore,
    DurationStatistics,
    ExperienceMetrics,
    LintIssue,
    PhaseDurationScore,
    PhaseStatistics,
    QualityMetrics,
    StabilityMetrics,
    StaticScanResult,
    StateHandlingMetrics,
    StateHandlingResult,
    SuccessRateMetrics,
)

__all__ = [
    "ANREvent",
    "CodeQualityMetrics",
    "ComplexityResult",
    "CoreFunctionCoverage",
    "CrashEvent",
    "DuplicationResult",
    "DurationScore",
    "DurationStatistics",
    "ExperienceMetrics",
    "LintIssue",
    "PhaseDurationScore",
    "PhaseStatistics",
    "QualityMetrics",
    "StabilityMetrics",
    "StaticScanResult",
    "StateHandlingMetrics",
    "StateHandlingResult",
    "SuccessRateMetrics",
    "compute_duration_statistics",
    "compute_experience",
    "compute_quality",
    "compute_success_rate",
    "score_backend_completeness",
    "score_code_quality",
    "score_core_function_coverage",
    "score_duration",
    "score_package_size",
    "score_stability",
    "score_state_handling",
]
