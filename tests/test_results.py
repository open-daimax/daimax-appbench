"""测试 evalapp.evaluation.results 模块的核心功能。

覆盖:
- GenerationCorrectnessMetrics 计算
- FailureRateMetrics 计算
- Reporter HTML 生成
- EvalRun 汇总
- 序列化/反序列化兼容性
"""

from __future__ import annotations

import json
import warnings


from evalapp.evaluation.results.models import (
    EvalRun,
    FrameworkResultCollection,
    GenerationCorrectnessMetrics,
    PromptResult,
    TestCaseResult,
    _compute_gc_from_results,
)
from evalapp.evaluation.results.models.report import build_report_data
from evalapp.evaluation.results import Reporter


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------


def _make_pr(
    *,
    prompt_id: str = "sample_001",
    platform: str = "android",
    gen_success: bool = True,
    build_status: str = "success",
    install_status: str = "success",
    launch_status: str = "success",
    complexity: str = "simple",
    test_results: list | None = None,
) -> PromptResult:
    """Create a PromptResult with sensible defaults for testing."""
    return PromptResult(
        prompt_id=prompt_id,
        platform=platform,
        generator_name="test",
        generation_success=gen_success,
        sample_complexity=complexity,
        result_data=FrameworkResultCollection(
            build_status=build_status,
            install_status=install_status,
            launch_status=launch_status,
        ),
        test_results=test_results or [],
    )


# ---------------------------------------------------------------------------
# Generation Correctness Tests
# ---------------------------------------------------------------------------


class TestGenerationCorrectness:
    """测试 _compute_gc_from_results 计算逻辑。"""

    def test_gc_all_success(self):
        """全部成功 -> 各项 100%。"""
        results = [_make_pr() for _ in range(3)]
        gc = _compute_gc_from_results(results)
        assert gc.total_samples == 3
        assert gc.generation_success_rate == 1.0
        assert gc.install_success_rate == 1.0
        assert gc.launch_success_rate == 1.0
        # composite = 0.45 + 0.20 + 0.35 = 1.0 -> 100%
        assert gc.composite_score == 100.0

    def test_gc_all_failed(self):
        """全部生成失败 -> 各项 0%。"""
        results = [_make_pr(gen_success=False, build_status="failed") for _ in range(3)]
        gc = _compute_gc_from_results(results)
        assert gc.generation_success_count == 0
        assert gc.install_success_count == 0
        assert gc.launch_success_count == 0
        assert gc.composite_score == 0.0

    def test_gc_mixed_results(self):
        """混合结果：部分成功部分失败。"""
        results = [
            _make_pr(gen_success=True),
            _make_pr(gen_success=False, build_status="failed"),
        ]
        gc = _compute_gc_from_results(results)
        assert gc.total_samples == 2
        assert gc.generation_success_count == 1
        assert gc.generation_success_rate == 0.5

    def test_gc_per_platform_breakdown(self):
        """按平台分解验证。"""
        results = [
            _make_pr(platform="android"),
            _make_pr(platform="ios"),
            _make_pr(platform="android", gen_success=False, build_status="failed"),
        ]
        gc = _compute_gc_from_results(results)
        assert "android" in gc.per_platform
        assert "ios" in gc.per_platform
        assert gc.per_platform["ios"].generation_success_rate == 1.0
        assert gc.per_platform["android"].generation_success_rate == 0.5

    def test_gc_per_complexity_breakdown(self):
        """按复杂度分解验证。"""
        results = [
            _make_pr(complexity="simple"),
            _make_pr(complexity="complex", gen_success=False, build_status="failed"),
        ]
        gc = _compute_gc_from_results(results)
        assert "simple" in gc.per_complexity
        assert gc.per_complexity["simple"].generation_success_rate == 1.0
        assert gc.per_complexity["complex"].generation_success_rate == 0.0

    def test_gc_composite_score_formula(self):
        """验证 composite_score = gen*45% + install*20% + launch*35%。"""
        # 2 samples: 1 full success, 1 gen success but install/launch fail
        results = [
            _make_pr(),
            _make_pr(install_status="failed", launch_status="failed"),
        ]
        gc = _compute_gc_from_results(results)
        # gen: 2/2=1.0, install: 1/2=0.5, launch: 1/2=0.5
        expected = round((1.0 * 0.45 + 0.5 * 0.20 + 0.5 * 0.35) * 100, 2)
        assert gc.composite_score == expected

    def test_gc_empty_run(self):
        """空列表 -> 空 metrics。"""
        gc = _compute_gc_from_results([])
        assert gc.total_samples == 0

    def test_gc_generation_success_with_unknown_build(self):
        """generation_success=True, build_status=unknown -> 视为生成成功。"""
        results = [_make_pr(build_status="unknown")]
        gc = _compute_gc_from_results(results)
        assert gc.generation_success_count == 1

    def test_gc_miniprogram_skipped_build_install(self):
        """小程序: build/install 跳过 -> 不视为失败。"""
        results = [
            _make_pr(
                platform="miniprogram",
                build_status="skipped",
                install_status="skipped",
                launch_status="success",
            ),
        ]
        gc = _compute_gc_from_results(results)
        assert gc.generation_success_count == 1
        assert gc.install_success_count == 1
        assert gc.launch_success_count == 1

    def test_gc_miniprogram_skipped_launch_fail(self):
        """小程序: build/install 跳过但 launch 失败。"""
        results = [
            _make_pr(
                platform="miniprogram",
                build_status="skipped",
                install_status="skipped",
                launch_status="failed",
            ),
        ]
        gc = _compute_gc_from_results(results)
        assert gc.generation_success_count == 1
        assert gc.install_success_count == 1
        assert gc.launch_success_count == 0

    def test_gc_mixed_platforms_with_miniprogram(self):
        """混合平台包含小程序。"""
        results = [
            _make_pr(platform="android"),
            _make_pr(
                platform="miniprogram",
                build_status="skipped",
                install_status="skipped",
                launch_status="success",
            ),
        ]
        gc = _compute_gc_from_results(results)
        assert gc.total_samples == 2
        assert gc.generation_success_count == 2
        assert gc.launch_success_count == 2

    def test_gc_serialization_roundtrip(self):
        """序列化/反序列化不丢失数据。"""
        results = [_make_pr(), _make_pr(gen_success=False, build_status="failed")]
        gc = _compute_gc_from_results(results)
        data = gc.model_dump()
        gc2 = GenerationCorrectnessMetrics.model_validate(data)
        assert gc2.total_samples == gc.total_samples
        assert gc2.composite_score == gc.composite_score


# ---------------------------------------------------------------------------
# Reporter Tests
# ---------------------------------------------------------------------------


class TestReporter:
    """测试 Reporter HTML 生成。"""

    def _make_run(self):
        """Create a minimal EvalRun with results for report generation."""
        from evalapp.evaluation.metrics import compute_success_rate, compute_quality, compute_experience
        run = EvalRun(generator_name="test", run_type="sample")
        pr = PromptResult(
            prompt_id="sample_001",
            platform="ios",
            generator_name="test",
            generation_success=True,
            test_results=[
                TestCaseResult(test_case_id="TC001", passed=True, status="PASS"),
                TestCaseResult(test_case_id="TC002", passed=False, status="FAIL"),
            ],
            result_data=FrameworkResultCollection(
                build_status="success",
                install_status="success",
                launch_status="success",
            ),
        )
        pr.success_rate = compute_success_rate(0.5, gen_ok=True, launch_ok=True)
        pr.quality = compute_quality(
            e2e_pass_rate=0.5,
            stability_score=100.0,
            e2e_pass_count=1,
            e2e_total_count=2,
        )
        pr.experience = compute_experience(duration_ms=300000)
        run.prompt_results.append(pr)
        run.compute_summary()
        return run

    def test_reporter_single_run(self):
        """单次运行报告生成不报错，且报告数据已注入前端模板。"""
        run = self._make_run()
        reporter = Reporter()
        html = reporter.generate_html_report(run, dataset_version="v1")
        assert "<!DOCTYPE html>" in html
        # 数据占位符已被报告 JSON 替换，且包含样本数据
        assert "__REPORT_DATA_PLACEHOLDER__" not in html
        assert "window.__REPORT_DATA__ = {" in html
        assert "sample_001" in html

    def test_reporter_comparison(self, tmp_path):
        """报告保存到文件。"""
        run = self._make_run()
        reporter = Reporter()
        path = reporter.save_html_report(run, tmp_path, dataset_version="v1")
        assert path.exists()
        assert path.name == "report.html"
        content = path.read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in content

    def test_gc_in_report(self):
        """报告数据中包含 generation correctness 指标。"""
        run = self._make_run()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            report_data = build_report_data(run, dataset_version="v1")
        # summary 中有 failure_rate_metrics
        assert report_data.summary is not None

    def test_gc_in_comparison_report(self):
        """build_report_data 应返回可序列化的 ReportData。"""
        run = self._make_run()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            report_data = build_report_data(run, dataset_version="v1")
        # ReportData 应能序列化为 JSON
        data_json = report_data.model_dump_json()
        assert data_json
        parsed = json.loads(data_json)
        assert "meta" in parsed
        assert "sample_results" in parsed
