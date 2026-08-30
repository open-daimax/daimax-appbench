"""报告重聚合后的顶层与平台指标一致性测试。"""

from evalapp.services.reporting import _sync_rebuilt_top_level_metrics


def test_sync_rebuilt_metrics_refreshes_duration_and_platform_summary():
    report_data = {
        "top_level_summary": {
            "mean_success_rate": 10.0,
            "mean_quality": 20.0,
            "mean_experience": 30.0,
            "mean_stability_score": 40.0,
            "mean_duration_ms": 885_000,
            "mean_aesthetics_score": 4.0,
            "per_platform": {"h5": {"mean_duration_ms": 885_000}},
        }
    }
    rebuilt = {
        "top_level_summary": {
            "mean_success_rate": 58.8,
            "mean_quality": 27.7,
            "mean_experience": 45.2,
            "mean_stability_score": 57.4,
            "mean_duration_ms": 1_153_431.1,
            "mean_aesthetics_score": 5.5,
            "per_platform": {"h5": {"mean_duration_ms": 1_153_431.1}},
        }
    }

    assert _sync_rebuilt_top_level_metrics(report_data, rebuilt) is True
    summary = report_data["top_level_summary"]
    assert summary["mean_duration_ms"] == 1_153_431.1
    assert summary["per_platform"]["h5"]["mean_duration_ms"] == 1_153_431.1
    assert summary["mean_aesthetics_score"] == 5.5


def test_sync_rebuilt_metrics_requires_platform_data():
    report_data = {"top_level_summary": {"mean_duration_ms": 885_000}}

    assert _sync_rebuilt_top_level_metrics(
        report_data,
        {"top_level_summary": {"mean_duration_ms": 1_153_431.1}},
    ) is False
    assert report_data["top_level_summary"]["mean_duration_ms"] == 885_000
