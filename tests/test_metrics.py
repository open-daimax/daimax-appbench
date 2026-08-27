"""测试 evalapp.evaluation.metrics 中的 duration 评分逻辑。

覆盖:
- score_duration 正常场景
- score_duration 部分数据缺失(partial data)
- compute_duration_statistics 聚合
"""

from __future__ import annotations


from evalapp.evaluation.metrics import score_duration, compute_duration_statistics
from evalapp.evaluation.results.models import DurationMetrics


class TestScoreDuration:
    """测试 score_duration 评分函数。"""

    def test_score_duration_fast(self):
        """非常快的时间应得满分(100)。"""
        d = DurationMetrics(total_ms=60_000)  # 1分钟
        result = score_duration(d)
        assert result.composite_score == 100.0

    def test_score_duration_slow(self):
        """超慢的时间应得低分。"""
        d = DurationMetrics(total_ms=3_500_000)  # ~58分钟
        result = score_duration(d)
        assert result.composite_score <= 5.0

    def test_score_duration_partial_data(self):
        """partial data: total_ms=None -> 得分0。"""
        d = DurationMetrics(total_ms=None)
        result = score_duration(d)
        assert result.composite_score == 0.0

    def test_score_duration_medium(self):
        """中等耗时应得到中间分数。"""
        d = DurationMetrics(total_ms=600_000)  # 10分钟
        result = score_duration(d)
        assert 20.0 < result.composite_score < 90.0

    def test_score_duration_timeout_flag(self):
        """超过30分钟应标记 is_timeout。"""
        d = DurationMetrics(total_ms=2_000_000)  # ~33分钟
        result = score_duration(d)
        assert result.is_timeout is True

    def test_score_duration_not_timeout(self):
        """未超过30分钟，is_timeout=False。"""
        d = DurationMetrics(total_ms=300_000)  # 5分钟
        result = score_duration(d)
        assert result.is_timeout is False


class TestComputeDurationStatistics:
    """测试 compute_duration_statistics 聚合统计。"""

    def test_empty_input(self):
        """空输入应返回默认值。"""
        stats = compute_duration_statistics([], [])
        assert stats.total_samples == 0

    def test_single_sample(self):
        """单个样本的统计。"""
        d = DurationMetrics(total_ms=300_000)
        ds = score_duration(d)
        stats = compute_duration_statistics([ds], [d])
        assert stats.total_samples == 1
        assert stats.total.mean_ms == 300_000

    def test_multiple_samples(self):
        """多个样本的平均值计算。"""
        durations = [
            DurationMetrics(total_ms=100_000),
            DurationMetrics(total_ms=200_000),
            DurationMetrics(total_ms=300_000),
        ]
        scores = [score_duration(d) for d in durations]
        stats = compute_duration_statistics(scores, durations)
        assert stats.total_samples == 3
        assert stats.total.mean_ms == 200_000
        assert stats.timeout_count == 0
