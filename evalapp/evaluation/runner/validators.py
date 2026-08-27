"""Result validation: verify results, compute metrics, and judge pass/fail."""

from __future__ import annotations

from ..metrics.models import (
    StabilityMetrics,
    SuccessRateMetrics,
    QualityMetrics,
    ExperienceMetrics,
)
from ..metrics import score_stability
from ...utils.logging import get_logger

logger = get_logger(__name__)


def compute_success_rate(result) -> SuccessRateMetrics:
    """Compute success rate metrics for a PromptResult."""
    from ..metrics import compute_success_rate as _compute

    # First-generation success rate: generation_success && launch_success
    rd = result.result_data
    gen_ok = result.generation_success

    if rd is not None:
        install_status = rd.install_status.lower()
        launch_status = rd.launch_status.lower()
        # 对于不需要原生安装的平台（h5 / miniprogram / expo_web），
        # install 步骤被跳过是预期的。但仍需检查 launch_status：
        # 如果 E2E 测试阶段的 TC_LAUNCH 失败（白屏 / 页面无法加载），
        # launch_status 会被推断为 "failed"，此时首次成功率应为 0。
        if install_status == "skipped":
            launch_ok = gen_ok and launch_status not in ("failed",)
        else:
            launch_ok = launch_status in ("success", "passed", "ok")
    else:
        launch_ok = False

    initial_rate = 1.0 if (gen_ok and launch_ok) else 0.0

    return _compute(
        initial_rate=initial_rate,
        gen_ok=gen_ok,
        launch_ok=launch_ok,
    )


def compute_quality(result, execution_result) -> QualityMetrics:
    """Compute quality metrics for a PromptResult."""
    from ..metrics import compute_quality as _compute

    # E2E test pass rate
    e2e_pass_rate = result.pass_rate
    e2e_pass_count = result.pass_count
    e2e_total_count = result.total_count

    # Stability score (from execution_result temp attribute)
    stability_score: float | None = None
    crash_count = 0
    anr_count = 0
    crash_free = True
    white_screen_count = 0

    if hasattr(execution_result, 'stability_metrics') and execution_result.stability_metrics:
        stability = execution_result.stability_metrics
        stability_score = stability.score  # may be None
        crash_count = stability.crash_count
        anr_count = stability.anr_count
        crash_free = stability.crash_free
        white_screen_count = stability.white_screen_count

    # Build/install/launch status from result_data
    rd = result.result_data
    build_status = rd.build_status if rd else "unknown"
    install_status = rd.install_status if rd else "unknown"
    launch_status = rd.launch_status if rd else "unknown"

    # requires_backend: 从 PromptResult 中读取
    requires_backend = getattr(result, 'requires_backend', False)

    # real_backend_pass: 从 test_results 的 verifications.real_backend.pass 中聚合
    # 优先使用请求级别的 pass_rate（新版数据），兼容旧版 pass boolean
    real_backend_pass: bool | None = None
    real_backend_pass_rate: float | None = None  # 后端验证通过率 (0.0-1.0)
    test_results = execution_result.test_results if execution_result else None
    if test_results:
        backend_total = 0
        rates = []
        for tr in test_results:
            if hasattr(tr, 'verifications') and tr.verifications and "real_backend" in tr.verifications:
                backend_total += 1
                rb = tr.verifications["real_backend"]
                rate = rb.get("pass_rate")
                if rate is not None:
                    # 新版数据：使用请求级别的通过率
                    rates.append(rate)
                else:
                    # 兼容旧版数据：pass=true → 1.0, pass=false → 0.0
                    rates.append(1.0 if rb.get("pass", False) else 0.0)
        if backend_total > 0:
            real_backend_pass_rate = sum(rates) / len(rates)
            real_backend_pass = real_backend_pass_rate > 0  # 至少有部分请求成功

    return _compute(
        e2e_pass_rate=e2e_pass_rate,
        stability_score=stability_score,
        e2e_pass_count=e2e_pass_count,
        e2e_total_count=e2e_total_count,
        crash_count=crash_count,
        anr_count=anr_count,
        crash_free=crash_free,
        build_status=build_status,
        install_status=install_status,
        launch_status=launch_status,
        white_screen_count=white_screen_count,
        requires_backend=requires_backend,
        real_backend_pass=real_backend_pass,
        real_backend_pass_rate=real_backend_pass_rate,
    )


def compute_experience(process_data, package_size_bytes: int = 0) -> ExperienceMetrics:
    """Compute experience metrics from process data."""
    from ..metrics import compute_experience as _compute

    # End-to-end duration (milliseconds)
    duration_ms = process_data.durations.total_ms or 0

    return _compute(
        duration_ms=duration_ms,
        package_size_bytes=package_size_bytes,
        token_input=process_data.token_input or 0,
        token_output=process_data.token_output or 0,
        token_total=process_data.token_total or 0,
    )


def compute_usability_metrics(
    sample,
    test_cases,
    execution_result,
    project_path: str = "",
    platform: str = "",
) -> None:
    """Compute stability metrics and store on execution_result.stability_metrics.

    Note: Does not return a value. Computes and stores as
    execution_result.stability_metrics for later use by compute_quality.
    """
    if execution_result is None:
        return

    test_results = execution_result.test_results
    total_runs = len(test_results) if test_results else 0

    # --- Stability metrics ---
    crash_count = len(execution_result.crash_events)
    anr_count = len(execution_result.anr_events)
    crash_rate = crash_count / total_runs if total_runs > 0 else 0.0
    anr_rate = anr_count / total_runs if total_runs > 0 else 0.0

    # --- White screen detection: read from TestCaseResult.verifications ---
    # Only count white screens from FAILED test cases.
    # If a test case passed, any detected "white screen" is a transient loading
    # frame (e.g. brief blank before content renders) — not a real white screen.
    white_screen_count = 0
    white_screen_evidence = []
    if test_results:
        for tr in test_results:
            if hasattr(tr, 'verifications') and tr.verifications and "white_screen" in tr.verifications:
                if tr.verifications["white_screen"].get("detected", False):
                    # Skip white screen from passed test cases — transient blank frame
                    if getattr(tr, 'passed', False):
                        logger.debug(
                            "Ignoring transient white screen in passed test case %s",
                            tr.test_case_id,
                        )
                        continue
                    white_screen_count += 1
                    white_screen_evidence.append(tr.test_case_id)

    stability = StabilityMetrics(
        crash_count=crash_count,
        anr_count=anr_count,
        total_test_runs=total_runs,
        crash_rate=crash_rate,
        anr_rate=anr_rate,
        crash_events=list(execution_result.crash_events),
        anr_events=list(execution_result.anr_events),
        crash_free=(crash_count == 0 and anr_count == 0),
        white_screen_count=white_screen_count,
        white_screen_evidence=white_screen_evidence,
    )
    stability.score = score_stability(stability)

    # Store as proper field on ExecutionResult
    execution_result.stability_metrics = stability

    if stability.score is None:
        logger.info(
            "Stability metrics: no data (test_runs=%d), crashes=%d, anrs=%d",
            total_runs,
            crash_count,
            anr_count,
        )
    else:
        logger.info(
            "Stability metrics: score=%.0f, crashes=%d, anrs=%d",
            stability.score,
            crash_count,
            anr_count,
        )


def filter_test_cases_by_end_case(test_cases: list, end_case: str) -> list:
    """Filter test cases up to and including end_case.

    Args:
        test_cases: List of test cases (should be sorted by ID).
        end_case: The ending test case ID (e.g., "TC003").

    Returns:
        Filtered list containing test cases from start to end_case (inclusive).
    """
    end_index = -1
    for i, tc in enumerate(test_cases):
        if tc.id == end_case:
            end_index = i
            break

    if end_index >= 0:
        return test_cases[:end_index + 1]
    else:
        logger.warning(
            "end_case '%s' not found in test cases. Executing all %d test cases.",
            end_case,
            len(test_cases)
        )
        return test_cases


def filter_test_cases_by_priority(test_cases: list, priority: str) -> list:
    """Filter test cases by priority.

    Args:
        test_cases: List of test cases.
        priority: Priority filter, e.g. "P0" means only P0 cases,
                  "P0,P1" means P0 and P1 cases.

    Returns:
        Filtered list. Returns all test cases if filter matches nothing.
    """
    # Support comma-separated multi-priority
    allowed = {p.strip().upper() for p in priority.split(",")}
    filtered = [tc for tc in test_cases if tc.priority.upper() in allowed]
    if not filtered:
        logger.warning(
            "priority '%s' matched no test cases. Executing all %d test cases.",
            priority,
            len(test_cases)
        )
        return test_cases
    return filtered
