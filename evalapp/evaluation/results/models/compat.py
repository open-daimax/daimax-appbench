"""Backward-compatible re-export shim (DEPRECATED).

.. deprecated:: 2.0
    Direct imports from ``evalapp.evaluation.results.models.compat`` are deprecated.
    Use ``from evalapp.evaluation.results.models import ...`` instead.
    This module will be removed in v3.0.

This file exists solely for backward compatibility with code that may
have imported from ``evalapp.evaluation.results.models.compat`` directly.
All public symbols are now defined in ``__init__.py``.
"""

# Re-export everything from the sub-modules for backward compat.
# New code should import from evalapp.evaluation.results.models directly.
from .execution import (  # noqa: F401
    DurationMetrics,
    E2EResult,
    EvalRun,
    FrameworkResultCollection,
    ProcessCollection,
    PromptResult,
    TestCaseResult,
    _compute_failure_rate_flat,
    _compute_gc_flat,
    _compute_gc_from_results,
    _determine_failure_stage,
    _is_status_skipped,
    _is_status_success,
    compute_failure_rate_metrics,
)
from .report import (  # noqa: F401
    ReportData,
    ReportMeta,
    ReportSampleResult,
    build_report_data,
)
from .summary import (  # noqa: F401
    EvalSummary,
    FailureCategory,
    FailureDetail,
    FailureRateMetrics,
    GenerationCorrectnessMetrics,
    _ENV_ERROR_KEYWORDS,
    _ERROR_TYPE_TO_CATEGORY,
    classify_failure,
)
