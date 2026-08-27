"""Summary and aggregation models for evaluation results.

Contains failure classification, failure rate metrics, generation correctness
metrics, and the aggregate EvalSummary model.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from ...metrics.models import DurationStatistics


# ---------------------------------------------------------------------------
# Failure classification & rate metrics  (V2 doc "失败分类" & "失败率指标")
# ---------------------------------------------------------------------------


class FailureCategory(str, Enum):
    """Failure classification per V2 evaluation plan.

    Maps to the 11 failure types defined in the design document:
    需求理解失败 / 规划失败 / 代码生成失败 / 构建失败 / 安装失败 /
    启动失败 / E2E执行失败 / 功能缺失/功能错误 / 稳定性问题 /
    环境问题 / 评测脚本问题
    """

    REQUIREMENT_UNDERSTANDING = "requirement_understanding"
    PLANNING = "planning"
    CODE_GENERATION = "code_generation"
    BUILD = "build"
    INSTALL = "install"
    LAUNCH = "launch"
    E2E_EXECUTION = "e2e_execution"
    FEATURE_MISSING = "feature_missing"
    STABILITY = "stability"
    ENVIRONMENT = "environment"
    EVAL_SCRIPT = "eval_script"
    UNKNOWN = "unknown"


# Mapping from ProcessCollection.error_type / step names to FailureCategory
_ERROR_TYPE_TO_CATEGORY: dict[str, FailureCategory] = {
    # Generator step names → category
    "requirements_analysis": FailureCategory.REQUIREMENT_UNDERSTANDING,
    "requirement_analysis": FailureCategory.REQUIREMENT_UNDERSTANDING,
    "requirement_understanding": FailureCategory.REQUIREMENT_UNDERSTANDING,
    "planning": FailureCategory.PLANNING,
    "plan": FailureCategory.PLANNING,
    "design": FailureCategory.PLANNING,
    "code_generation": FailureCategory.CODE_GENERATION,
    "codegen": FailureCategory.CODE_GENERATION,
    "code_gen": FailureCategory.CODE_GENERATION,
    "generation_failed": FailureCategory.CODE_GENERATION,
    "build": FailureCategory.BUILD,
    "compile": FailureCategory.BUILD,
    "install": FailureCategory.INSTALL,
    "installation": FailureCategory.INSTALL,
    "launch": FailureCategory.LAUNCH,
    "startup": FailureCategory.LAUNCH,
    "e2e": FailureCategory.E2E_EXECUTION,
    "e2e_test": FailureCategory.E2E_EXECUTION,
    "test_execution": FailureCategory.E2E_EXECUTION,
    "collector_error": FailureCategory.EVAL_SCRIPT,
    "eval_script": FailureCategory.EVAL_SCRIPT,
    "environment": FailureCategory.ENVIRONMENT,
    "infra": FailureCategory.ENVIRONMENT,
    "emulator": FailureCategory.ENVIRONMENT,
}

# Keywords in error_message that hint at environment / infra issues
_ENV_ERROR_KEYWORDS = [
    "emulator", "simulator", "device not found", "adb",
    "timeout waiting", "connection refused", "no devices",
    "sdk", "ndk", "gradle daemon",
]


def classify_failure(
    error_type: str,
    error_message: str,
    stage: str = "",
) -> FailureCategory:
    """Classify a failure into a FailureCategory.

    Uses a priority cascade:
    1. Exact match on error_type
    2. Stage-based inference (generation/build/install/launch)
    3. Keyword matching in error_message
    4. Falls back to UNKNOWN
    """
    # 1. Exact match on error_type
    et_lower = error_type.strip().lower()
    if et_lower in _ERROR_TYPE_TO_CATEGORY:
        return _ERROR_TYPE_TO_CATEGORY[et_lower]

    # 2. Stage-based inference
    stage_lower = stage.strip().lower()
    stage_map: dict[str, FailureCategory] = {
        "generation": FailureCategory.CODE_GENERATION,
        "build": FailureCategory.BUILD,
        "install": FailureCategory.INSTALL,
        "launch": FailureCategory.LAUNCH,
        "e2e": FailureCategory.E2E_EXECUTION,
    }
    if stage_lower in stage_map:
        return stage_map[stage_lower]

    # 3. Keyword matching in error_message for env issues
    msg_lower = error_message.lower()
    if any(kw in msg_lower for kw in _ENV_ERROR_KEYWORDS):
        return FailureCategory.ENVIRONMENT

    return FailureCategory.UNKNOWN


class FailureDetail(BaseModel):
    """Detailed record of a single failure instance."""

    item_id: str = ""
    platform: str = ""
    category: FailureCategory = FailureCategory.UNKNOWN
    stage: str = ""  # pipeline stage where failure occurred
    error_type: str = ""  # raw error_type from process data
    error_message: str = ""  # human-readable error description


class FailureRateMetrics(BaseModel):
    """Per-stage failure rate metrics per V2 evaluation plan.

    Tracks failure rates across five pipeline stages:
    - 需求理解失败率: tasks without valid understanding output
    - 规划失败率: tasks without valid planning output
    - 生成失败率: tasks that failed to produce a buildable project
    - 安装失败率: tasks where installation failed
    - 启动失败率: tasks where launch failed

    Also tracks failure reason distribution for root-cause analysis.
    """

    total_samples: int = 0

    # Per-stage failure counts
    requirement_understanding_failure_count: int = 0
    planning_failure_count: int = 0
    generation_failure_count: int = 0
    install_failure_count: int = 0
    launch_failure_count: int = 0

    # Per-stage failure rates (count / total_samples)
    requirement_understanding_failure_rate: float = 0.0
    planning_failure_rate: float = 0.0
    generation_failure_rate: float = 0.0
    install_failure_rate: float = 0.0
    launch_failure_rate: float = 0.0

    # Failure reason distribution: category -> count
    failure_reason_distribution: dict[str, int] = Field(default_factory=dict)

    # All failure details
    failures: list[FailureDetail] = Field(default_factory=list)

    # Per-platform breakdown (flat, no nested breakdowns)
    per_platform: dict[str, FailureRateMetrics] = Field(default_factory=dict)
    # Per-complexity breakdown
    per_complexity: dict[str, FailureRateMetrics] = Field(default_factory=dict)


class GenerationCorrectnessMetrics(BaseModel):
    """Engineering generation correctness metrics (V2 doc section 2).

    Tracks success rates across the generation pipeline stages:
    - Generation success rate (includes build)
    - Installation success rate
    - Launch success rate

    Composite score = generation_success_rate * 45% + install_success_rate * 20% + launch_success_rate * 35%
    """

    total_samples: int = 0
    generation_success_count: int = 0
    install_success_count: int = 0
    launch_success_count: int = 0
    generation_success_rate: float = 0.0
    install_success_rate: float = 0.0
    launch_success_rate: float = 0.0
    composite_score: float = 0.0

    # Per-platform breakdown
    per_platform: dict[str, GenerationCorrectnessMetrics] = Field(
        default_factory=dict
    )
    # Per-complexity breakdown
    per_complexity: dict[str, GenerationCorrectnessMetrics] = Field(
        default_factory=dict
    )

    # Failure details for attribution
    generation_failures: list[dict[str, str]] = Field(default_factory=list)
    install_failures: list[dict[str, str]] = Field(default_factory=list)
    launch_failures: list[dict[str, str]] = Field(default_factory=list)


class EvalSummary(BaseModel):
    """Aggregate summary of an evaluation run."""
    total_prompts: int = 0
    total_test_cases: int = 0
    total_passed: int = 0
    total_failed: int = 0
    overall_pass_rate: float = 0.0
    per_platform_pass_rate: dict[str, float] = Field(default_factory=dict)
    per_category_pass_rate: dict[str, float] = Field(default_factory=dict)
    duration_statistics: DurationStatistics = Field(
        default_factory=DurationStatistics
    )
    failure_rate_metrics: FailureRateMetrics = Field(
        default_factory=FailureRateMetrics
    )
    top_level_summary: dict[str, Any] = Field(default_factory=dict)  # 新增: 顶层指标汇总
