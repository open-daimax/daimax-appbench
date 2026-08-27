"""测试 evalapp.evaluation.metrics.collectors.code_quality 模块。

覆盖:
- collect_code_quality_metrics 基本逻辑
- _aggregate_metrics 聚合函数
- CodeQualityMetrics 数据模型
- 各平台静态分析工具的错误处理
"""

from __future__ import annotations


import pytest

from evalapp.evaluation.metrics.collectors.code_quality import (
    collect_code_quality_metrics,
    _aggregate_metrics,
)
from evalapp.evaluation.metrics.models import (
    CodeQualityMetrics,
    ComplexityResult,
    DuplicationResult,
    StaticScanResult,
)


class TestCodeQualityMetricsModel:
    """测试 CodeQualityMetrics 数据模型。"""

    def test_default_values(self):
        """默认值应全部为 0。"""
        m = CodeQualityMetrics()
        assert m.total_issues == 0
        assert m.error_count == 0
        assert m.warning_count == 0
        assert m.info_count == 0
        assert m.convention_compliance_rate == 0.0
        assert m.score == 0.0

    def test_loads_minimal_payload(self):
        """可用空字典反序列化（向后兼容）。"""
        m = CodeQualityMetrics.model_validate({})
        assert m.total_issues == 0

    def test_score_bounds(self):
        """score 字段的边界约束。"""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            CodeQualityMetrics(score=101)
        with pytest.raises(ValidationError):
            CodeQualityMetrics(score=-1)


class TestAggregateMetrics:
    """测试 _aggregate_metrics 聚合函数。"""

    def test_empty_results(self):
        """空输入应返回零值。"""
        result = _aggregate_metrics([], ComplexityResult(), DuplicationResult())
        assert result.total_issues == 0
        assert result.convention_compliance_rate == 0.0

    def test_single_scan_result(self):
        """单个扫描结果应正确聚合。"""
        scan = StaticScanResult(
            tool="eslint",
            success=True,
            total_issues=10,
            error_count=2,
            warning_count=5,
            info_count=3,
        )
        result = _aggregate_metrics([scan], ComplexityResult(), DuplicationResult())
        assert result.total_issues == 10
        assert result.error_count == 2
        assert result.warning_count == 5
        # compliance = 1 - (2+5)/10 = 0.3
        assert result.convention_compliance_rate == 0.3

    def test_with_complexity(self):
        """包含复杂度分析结果。"""
        complexity = ComplexityResult(
            success=True,
            total_functions=20,
            functions_over_threshold=4,
            avg_complexity=8.5,
            max_complexity=25.0,
        )
        result = _aggregate_metrics([], complexity, DuplicationResult())
        assert result.avg_complexity == 8.5
        assert result.max_complexity == 25.0
        # high_complexity_ratio = 4/20 = 0.2
        assert result.high_complexity_ratio == 0.2

    def test_with_duplication(self):
        """包含重复度检测结果。"""
        duplication = DuplicationResult(
            success=True,
            duplication_rate=0.15,
        )
        result = _aggregate_metrics([], ComplexityResult(), duplication)
        assert result.duplication_rate == 0.15

    def test_failed_scan_ignored(self):
        """失败的扫描结果不计入聚合。"""
        scan_ok = StaticScanResult(
            tool="eslint",
            success=True,
            total_issues=5,
            error_count=1,
            warning_count=2,
            info_count=2,
        )
        scan_fail = StaticScanResult(
            tool="swiftlint",
            success=False,
            total_issues=100,  # 这些不应被计入
            error_count=50,
        )
        result = _aggregate_metrics([scan_ok, scan_fail], ComplexityResult(), DuplicationResult())
        assert result.total_issues == 5
        assert result.error_count == 1


class TestCollectCodeQualityMetrics:
    """测试 collect_code_quality_metrics 公共 API。"""

    def test_unsupported_platform_returns_metrics(self, tmp_path):
        """不支持的平台应返回空 metrics（不抛异常）。"""
        result = collect_code_quality_metrics(
            str(tmp_path), "web",
            skip_complexity=True,
            skip_duplication=True,
        )
        assert isinstance(result, CodeQualityMetrics)

    def test_android_without_gradlew(self, tmp_path):
        """Android 项目无 gradlew 应在扫描结果中标记失败。"""
        result = collect_code_quality_metrics(
            str(tmp_path), "android",
            skip_complexity=True,
            skip_duplication=True,
        )
        assert isinstance(result, CodeQualityMetrics)
        # scan_results 中应有一条失败记录
        assert len(result.scan_results) == 1
        assert result.scan_results[0].success is False
        assert "gradlew" in result.scan_results[0].error_message
