"""Data models for top-level evaluation metrics.

Covers three top-level metrics:
- Success Rate: initial generation + issue fix + requirement extension
- Quality: functionality completeness + stability + compliance
- Experience: end-to-end duration
"""

from __future__ import annotations

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from . import rules


# ---------------------------------------------------------------------------
# Stability metrics
# ---------------------------------------------------------------------------


class CrashEvent(BaseModel):
    """A single crash event detected from device logs."""

    timestamp: str = ""
    signal: str = ""  # e.g. SIGSEGV, SIGABRT
    process: str = ""
    message: str = ""


class ANREvent(BaseModel):
    """A single ANR (Application Not Responding) event from device logs."""

    timestamp: str = ""
    process: str = ""
    reason: str = ""
    message: str = ""


class StabilityMetrics(BaseModel):
    """Aggregated stability metrics for one evaluation item.

    Scoring rules (per V2 design doc section 3.1):
    - No crashes, no ANR, core flow passes stably: 90-100
    - Occasional issues that don't block main flow: 70-89
    - Main flow has clear stability problems: 40-69
    - Frequent crashes or unusable: 0-39
    """

    crash_count: int = 0
    anr_count: int = 0
    total_test_runs: int = 0
    crash_rate: float = 0.0  # crash_count / total_test_runs
    anr_rate: float = 0.0  # anr_count / total_test_runs
    crash_events: list[CrashEvent] = Field(default_factory=list)
    anr_events: list[ANREvent] = Field(default_factory=list)
    crash_free: bool = True
    score: float = Field(default=0.0, ge=0, le=100)
    
    # 预留: 白屏检测(待实现)
    white_screen_count: int = 0
    white_screen_evidence: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Functionality metrics
# ---------------------------------------------------------------------------


class CoreFunctionCoverage(BaseModel):
    """Core function coverage rate for one evaluation item.

    Maps sample baseline ``core_functions`` to E2E test results to
    determine which core functions are actually exercised and passing.

    Scoring rules (per V2 design doc section 3.2):
    - All core functions present, main tasks completable: 90-100
    - Minor non-core gaps: 75-89
    - Some core functions missing or broken: 50-74
    - Core functions unusable: 0-49
    """

    total_functions: int = 0
    covered_functions: int = 0
    coverage_rate: float = 0.0
    function_results: dict[str, str] = Field(default_factory=dict)
    # function_name -> "covered" | "failed" | "missing"
    score: float = Field(default=0.0, ge=0, le=100)


class StateHandlingResult(BaseModel):
    """Result of checking one state type."""

    state_type: str  # "empty_state", "success_state", "error_state", "loading_state"
    handled: bool = False
    details: str = ""


class StateHandlingMetrics(BaseModel):
    """State handling completeness for one evaluation item.

    Checks whether the app handles standard UI states:
    empty state, success state, error/failure state, and loading state.

    Scoring rules (per V2 design doc section 3.2):
    - All states handled: 90-100
    - Most states handled: 75-89
    - Some states handled: 50-74
    - States largely unhandled: 0-49
    """

    total_states: int = 0
    handled_states: int = 0
    completeness_rate: float = 0.0
    state_results: list[StateHandlingResult] = Field(default_factory=list)
    score: float = Field(default=0.0, ge=0, le=100)


# ---------------------------------------------------------------------------
# Code quality metrics  (V2 doc section 3.3)
# ---------------------------------------------------------------------------


class LintIssue(BaseModel):
    """A single issue reported by a static analysis tool."""

    rule_id: str = ""  # e.g. "MissingPermission", "trailing_whitespace"
    severity: str = ""  # "error", "warning", "info"
    message: str = ""
    file: str = ""
    line: int = 0
    column: int = 0
    source: str = ""  # tool name: "android_lint", "swiftlint", "detekt"


class StaticScanResult(BaseModel):
    """Aggregated results from one static analysis tool run."""

    tool: str = ""  # "android_lint", "swiftlint", "detekt"
    success: bool = False
    error_count: int = 0
    warning_count: int = 0
    info_count: int = 0
    total_issues: int = 0
    issues: list[LintIssue] = Field(default_factory=list)
    raw_output_path: str = ""  # path to the raw report file
    error_message: str = ""  # non-empty if tool execution failed


class ComplexityResult(BaseModel):
    """Cyclomatic complexity analysis results."""

    tool: str = "lizard"  # analysis tool used
    success: bool = False
    total_functions: int = 0
    avg_complexity: float = 0.0
    max_complexity: float = 0.0
    functions_over_threshold: int = 0  # functions with CC > threshold
    complexity_threshold: int = 15  # default threshold
    high_complexity_functions: list[dict[str, object]] = Field(
        default_factory=list
    )  # [{"name": ..., "complexity": ..., "file": ..., "line": ...}]
    error_message: str = ""


class DuplicationResult(BaseModel):
    """Duplicate code detection results."""

    tool: str = "jscpd"  # detection tool used
    success: bool = False
    total_lines: int = 0
    duplicated_lines: int = 0
    duplication_rate: float = 0.0  # duplicated_lines / total_lines
    clone_count: int = 0  # number of clone groups
    clones: list[dict[str, object]] = Field(
        default_factory=list
    )  # [{"source_file": ..., "target_file": ..., "lines": ...}]
    error_message: str = ""


class CodeQualityMetrics(BaseModel):
    """Combined code quality metrics for one evaluation item.

    Per V2 design doc section 3.3, code quality uses
    "rule-based checking (80%) + AI review (20%)".

    This model covers the rule-based (80%) portion:
    - Static scan warning count (P0)
    - Code convention compliance rate (P0)
    - Cyclomatic complexity (P1)
    - Duplicate code ratio (P1)

    Scoring bands:
    - Few warnings, clear structure, manageable complexity: 90-100
    - Minor convention or structure issues: 75-89
    - Notable quality issues but maintainable: 50-74
    - Chaotic code, high risk: 0-49
    """

    # Static scan summary
    total_issues: int = 0
    error_count: int = 0
    warning_count: int = 0
    info_count: int = 0
    convention_compliance_rate: float = 0.0  # 1.0 - (error+warning)/total_scanned_files

    # Complexity summary
    avg_complexity: float = 0.0
    max_complexity: float = 0.0
    high_complexity_ratio: float = 0.0  # ratio of functions over threshold

    # Duplication summary
    duplication_rate: float = 0.0

    # Detailed tool results
    scan_results: list[StaticScanResult] = Field(default_factory=list)
    complexity_result: ComplexityResult = Field(default_factory=ComplexityResult)
    duplication_result: DuplicationResult = Field(default_factory=DuplicationResult)

    # Composite score (rule-based portion, 0-100)
    score: float = Field(default=0.0, ge=0, le=100)


# ---------------------------------------------------------------------------
# Composite usability metrics
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Duration scoring metrics  (V2 doc "生成成本 > 阶段耗时")
# ---------------------------------------------------------------------------


class PhaseDurationScore(BaseModel):
    """Duration score for a single phase.

    Scoring: shorter duration → higher score (0-100).
    Uses configurable thresholds; below *excellent* threshold → 100,
    above *poor* threshold → 0, linear interpolation in between.
    """

    duration_ms: float | None = None  # actual stored values are floats (e.g. 13388.26)
    score: float = Field(default=0.0, ge=0, le=100)


class DurationScore(BaseModel):
    """Per-sample duration scoring (V2 doc section 生成成本 > 阶段耗时)."""

    total: PhaseDurationScore = Field(default_factory=PhaseDurationScore)
    composite_score: float = Field(default=0.0, ge=0, le=100)  # equals total.score
    is_timeout: bool = False  # True if total_ms exceeds timeout threshold


class PhaseStatistics(BaseModel):
    """Aggregate statistics for one phase across multiple samples."""

    count: int = 0  # number of samples with data
    mean_ms: float = 0.0
    median_ms: float = 0.0
    p90_ms: float = 0.0
    p95_ms: float = 0.0
    min_ms: float = 0.0
    max_ms: float = 0.0


class DurationStatistics(BaseModel):
    """Aggregate duration statistics across an evaluation run."""

    total_samples: int = 0
    total: PhaseStatistics = Field(default_factory=PhaseStatistics)
    timeout_count: int = 0
    timeout_rate: float = 0.0  # timeout_count / total_samples
    mean_score: float = 0.0  # average composite duration score


# ---------------------------------------------------------------------------
# Top-level metrics (新指标体系)
# ---------------------------------------------------------------------------


class SuccessRateMetrics(BaseModel):
    """Top-level success rate metrics - weighted average of three sub-dimensions."""

    # 子指标1: 首次生成成功率(当前实现)
    initial_generation_rate: float = Field(default=0.0, ge=0, le=100)  # 首页无崩溃/白屏
    initial_generation_weight: float = rules.SUCCESS_RATE_INITIAL_GENERATION_WEIGHT
    initial_generation_reason: str = ""  # 得分原因说明

    # 子指标2: 问题修复成功率(预留)
    issue_fix_rate: float = Field(default=0.0, ge=0, le=100)  # 多轮修复成功率
    issue_fix_weight: float = rules.SUCCESS_RATE_ISSUE_FIX_WEIGHT
    issue_fix_count: int = 0  # 修复尝试次数
    issue_fix_success_count: int = 0  # 修复成功次数
    issue_fix_reason: str = ""  # 得分原因说明

    # 子指标3: 补充需求成功率(预留)
    requirement_extension_rate: float = Field(default=0.0, ge=0, le=100)  # 补充需求成功率
    requirement_extension_weight: float = rules.SUCCESS_RATE_REQUIREMENT_EXTENSION_WEIGHT
    requirement_extension_count: int = 0
    requirement_extension_success_count: int = 0
    requirement_extension_reason: str = ""  # 得分原因说明

    # 加权综合成功率
    composite_score: float = Field(default=0.0, ge=0, le=100)


class QualityMetrics(BaseModel):
    """Top-level functionality completeness metrics - deduction scoring model.

    Formula: functionality completeness = use-case completeness - stability deduction - backend deduction
    - Stability deduction = (1 - stability_score/100) × use-case completeness × 0.2
    - Backend deduction = (1 - backend_completeness/100) × use-case completeness × 0.3
    - Missing items incur no deduction; minimum is 0
    """

    # 允许以字段名或别名加载，保证新旧命名兼容
    model_config = ConfigDict(populate_by_name=True)

    # 子指标1: 用例完整性(E2E测试通过率)
    # 兼容别名: functionality_completeness(旧名) / functionality_score(旧名) / quality_score(跨层同义)
    usecase_completeness: float = Field(
        default=0.0,
        ge=0,
        le=100,
        validation_alias=AliasChoices(
            "usecase_completeness", "functionality_completeness", "functionality_score", "quality_score"
        ),
    )  # E2E通过率
    e2e_pass_count: int = 0
    e2e_total_count: int = 0
    usecase_reason: str = ""  # 得分原因说明

    # 子指标2: 运行稳定性
    stability_score: float | None = Field(default=None, ge=0, le=100)  # 复用现有StabilityMetrics.score, None表示无数据
    crash_count: int = 0
    anr_count: int = 0
    white_screen_count: int = 0
    crash_free: bool = True
    stability_reason: str = ""  # 得分原因说明

    # 子指标2.5: 后端完整性(requires_backend=true时参与扣分)
    backend_completeness: float | None = Field(default=None, ge=0, le=100)  # 0-100, None表示不适用(requires_backend=false)
    backend_completeness_reason: str = ""  # 得分原因说明

    # 子指标3: 合规性评分(完全预留)
    compliance_score: float = Field(default=0.0, ge=0, le=100)  # 数据安全/上架规范,预留字段
    compliance_issues: list[str] = Field(default_factory=list)
    compliance_reason: str = ""  # 得分原因说明

    # 扣分明细
    stability_deduction: float = Field(default=0.0, ge=0, description="稳定性扣分")
    backend_deduction: float = Field(default=0.0, ge=0, description="后端完整性扣分")

    # 减法扣分综合得分
    composite_score: float = Field(default=0.0, ge=0, le=100)


class ExperienceMetrics(BaseModel):
    """Top-level experience metrics - three dimensions."""

    # 允许以字段名或别名加载，保证新旧命名兼容
    model_config = ConfigDict(populate_by_name=True)

    # 子指标1: 端到端耗时
    # 兼容别名: duration_ms(报告层同义字段)
    end_to_end_duration_ms: float = Field(
        default=0.0,
        validation_alias=AliasChoices("end_to_end_duration_ms", "duration_ms"),
    )  # 从输入需求到可运行应用的总时间(ms, 浮点)
    duration_score: float = Field(default=0.0, ge=0, le=100)  # 基于阈值评分(复用现有逻辑)
    duration_reason: str = ""  # 得分原因说明

    # 子指标2: 包大小
    package_size_bytes: int = 0        # 构建产物大小(字节)
    package_size_score: float = Field(default=0.0, ge=0, le=100)  # 基于阈值评分 0-100
    package_size_reason: str = ""      # 得分原因说明

    # 子指标3: Token消耗
    token_input: int = 0          # 输入token数
    token_output: int = 0         # 输出token数
    token_total: int = 0          # 总token数

    # 子指标4: UI美观度（基于截图的视觉质量评估）
    aesthetics_score: float | None = None  # 0-10 综合分，None 表示未评分
    aesthetics_reason: str = ""  # 一句话评语
    aesthetics_issues: list[str] = Field(default_factory=list)  # 扣分明细
    aesthetics_dimensions: dict = Field(default_factory=dict)  # 子维度得分
    aesthetics_rule_version: str = ""  # 使用的规则版本
    aesthetics_scored_frames: list[str] = Field(default_factory=list)  # 评分截图相对路径

    # 综合体验得分(耗时60% + 包大小20% + 美观度20%, 缺失维度动态归一化, Token仅展示不参与评分)
    composite_score: float = Field(default=0.0, ge=0, le=100)


