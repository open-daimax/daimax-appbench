"""测试 failure rate 指标计算逻辑。

覆盖:
- compute_failure_rate_metrics 各阶段失败率
- 失败分类 classify_failure
- per_platform 分解
- 报告中 failure_rate_metrics 展示
- 全部成功时无 failure section
"""

from __future__ import annotations

import warnings


from evalapp.evaluation.results.models import (
    EvalRun,
    FrameworkResultCollection,
    ProcessCollection,
    PromptResult,
    compute_failure_rate_metrics,
)
from evalapp.evaluation.results.models.summary import classify_failure, FailureCategory
from evalapp.evaluation.results.models.report import build_report_data
from evalapp.evaluation.metrics import compute_success_rate, compute_quality, compute_experience


def _make_pr(
    *,
    prompt_id: str = "sample_001",
    platform: str = "android",
    gen_success: bool = True,
    build_status: str = "success",
    install_status: str = "success",
    launch_status: str = "success",
    error_type: str = "",
    error_message: str = "",
    complexity: str = "simple",
) -> PromptResult:
    """创建一个带有 process data 的 PromptResult。"""
    return PromptResult(
        prompt_id=prompt_id,
        platform=platform,
        generator_name="test",
        generation_success=gen_success,
        sample_complexity=complexity,
        error_message=error_message,
        process_data=ProcessCollection(
            error_type=error_type,
            error_message=error_message,
        ),
        result_data=FrameworkResultCollection(
            build_status=build_status,
            install_status=install_status,
            launch_status=launch_status,
        ),
    )


class TestFailureRateComputation:
    """测试 compute_failure_rate_metrics。"""

    def test_failure_rate_all_success(self):
        """全部成功 -> 各项失败率为0。"""
        results = [_make_pr() for _ in range(3)]
        metrics = compute_failure_rate_metrics(results)
        assert metrics.total_samples == 3
        assert metrics.generation_failure_rate == 0.0
        assert metrics.install_failure_rate == 0.0
        assert metrics.launch_failure_rate == 0.0
        assert len(metrics.failures) == 0

    def test_failure_rate_generation_failure(self):
        """生成失败 -> generation_failure_rate > 0。"""
        results = [
            _make_pr(gen_success=False, error_type="code_generation"),
            _make_pr(),
        ]
        metrics = compute_failure_rate_metrics(results)
        assert metrics.generation_failure_count == 1
        assert metrics.generation_failure_rate == 0.5

    def test_failure_rate_install_failure(self):
        """安装失败 -> install_failure_rate > 0。"""
        results = [
            _make_pr(install_status="failed", launch_status="unknown"),
            _make_pr(),
        ]
        metrics = compute_failure_rate_metrics(results)
        assert metrics.install_failure_count == 1
        assert metrics.install_failure_rate == 0.5

    def test_failure_rate_launch_failure(self):
        """启动失败 -> launch_failure_rate > 0。"""
        results = [
            _make_pr(launch_status="failed"),
            _make_pr(),
        ]
        metrics = compute_failure_rate_metrics(results)
        assert metrics.launch_failure_count == 1
        assert metrics.launch_failure_rate == 0.5

    def test_failure_rate_per_platform_in_report(self):
        """每个平台有独立的失败率统计。"""
        results = [
            _make_pr(platform="android", gen_success=False, error_type="build"),
            _make_pr(platform="android"),
            _make_pr(platform="ios"),
        ]
        metrics = compute_failure_rate_metrics(results)
        assert "android" in metrics.per_platform
        assert "ios" in metrics.per_platform
        assert metrics.per_platform["android"].generation_failure_count == 1
        assert metrics.per_platform["ios"].generation_failure_count == 0

    def test_failure_rate_in_report(self):
        """EvalRun.compute_summary 应填充 failure_rate_metrics。"""
        run = EvalRun(generator_name="test", run_type="sample")
        pr = _make_pr(gen_success=False, error_type="build")
        pr.success_rate = compute_success_rate(0, gen_ok=False, launch_ok=False)
        pr.quality = compute_quality(e2e_pass_rate=0, stability_score=None, e2e_pass_count=0, e2e_total_count=0)
        pr.experience = compute_experience(duration_ms=60000)
        run.prompt_results.append(pr)
        run.compute_summary()

        fm = run.summary.failure_rate_metrics
        assert fm.total_samples == 1
        assert fm.generation_failure_count == 1

    def test_failure_rate_in_comparison_report(self):
        """build_report_data 中应包含 failure 信息。"""
        run = EvalRun(generator_name="test", run_type="sample")
        pr = _make_pr(gen_success=False, error_type="build")
        pr.success_rate = compute_success_rate(0, gen_ok=False, launch_ok=False)
        pr.quality = compute_quality(e2e_pass_rate=0, stability_score=None, e2e_pass_count=0, e2e_total_count=0)
        pr.experience = compute_experience(duration_ms=60000)
        run.prompt_results.append(pr)
        run.compute_summary()

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            report_data = build_report_data(run, dataset_version="v1")
        assert report_data.summary.failure_rate_metrics.total_samples == 1

    def test_no_failure_section_when_all_success(self):
        """全部成功时 failures 列表为空。"""
        results = [_make_pr() for _ in range(5)]
        metrics = compute_failure_rate_metrics(results)
        assert metrics.failures == []
        assert metrics.failure_reason_distribution == {}


class TestClassifyFailure:
    """测试 classify_failure 分类函数。"""

    def test_classify_build_error(self):
        cat = classify_failure("build", "")
        assert cat == FailureCategory.BUILD

    def test_classify_install_error(self):
        cat = classify_failure("install", "")
        assert cat == FailureCategory.INSTALL

    def test_classify_environment_by_keyword(self):
        cat = classify_failure("", "device not found on adb")
        assert cat == FailureCategory.ENVIRONMENT

    def test_classify_unknown_fallback(self):
        cat = classify_failure("", "something random")
        assert cat == FailureCategory.UNKNOWN

    def test_classify_with_stage(self):
        cat = classify_failure("", "", stage="generation")
        assert cat == FailureCategory.CODE_GENERATION
