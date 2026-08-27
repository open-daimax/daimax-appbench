"""测试 sample_data.consolidate_sample_report 自包含报告合并功能。"""

import json
from pathlib import Path

import pytest

from evalapp.workspace.sample_data import (
    consolidate_sample_report,
    consolidate_all_sample_reports,
    write_generation,
    write_evaluation,
    write_scores,
)


@pytest.fixture
def workspace(tmp_path):
    """创建一个包含单个样本的工作区临时目录。"""
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


def _write_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class TestConsolidateSampleReport:
    """测试 consolidate_sample_report 函数。"""

    def test_consolidate_from_generation_only(self, workspace):
        """仅有 generation 数据时，合并后保留生成字段，其余为 null。"""
        gen_data = {
            "sample_id": "TestApp",
            "generator": "custom_gen",
            "duration_ms": 120000,
            "platform_durations": {"android": 120000},
            "token_input": 5000,
            "token_output": 500,
            "token_total": 5500,
        }
        write_generation(workspace, "TestApp", gen_data)

        consolidate_sample_report(workspace, "TestApp")

        report_path = workspace / "TestApp" / "sample_report.json"
        assert report_path.exists()
        report = json.loads(report_path.read_text())

        # 生成字段保留
        assert report["sample_id"] == "TestApp"
        assert report["generator"] == "custom_gen"
        assert report["duration_ms"] == 120000
        # 元数据字段存在但为 null
        assert report["sample_title"] is None
        assert report["complexity"] is None
        assert "evaluated_at" in report

    def test_consolidate_merges_scores(self, workspace):
        """合并 scores.json 中的评分数据到 platforms 子键。"""
        gen_data = {
            "sample_id": "TestApp",
            "generator": "custom_gen",
            "duration_ms": 100000,
        }
        write_generation(workspace, "TestApp", gen_data)

        scores_data = {
            "sample_id": "TestApp",
            "platforms": {
                "android": {
                    "success_rate_score": 80.0,
                    "quality_score": 75.0,
                    "experience_score": 70.0,
                    "stability_score": 100.0,
                    "launch_screenshot": "screenshots/launch_android.png",
                    "requires_backend": False,
                    "backend_completeness": None,
                    "aesthetics_score": 85.0,
                    "aesthetics_reason": "Good design",
                },
            },
        }
        write_scores(workspace, "TestApp", scores_data)

        consolidate_sample_report(workspace, "TestApp")

        report = json.loads((workspace / "TestApp" / "sample_report.json").read_text())
        assert "platforms" in report
        assert "android" in report["platforms"]
        plat = report["platforms"]["android"]
        assert plat["success_rate_score"] == 80.0
        assert plat["quality_score"] == 75.0
        assert plat["aesthetics_score"] == 85.0

    def test_consolidate_merges_evaluation(self, workspace):
        """合并 evaluation.json 中的评测数据到 platforms 子键。"""
        gen_data = {
            "sample_id": "TestApp",
            "generator": "custom_gen",
            "duration_ms": 100000,
        }
        write_generation(workspace, "TestApp", gen_data)

        eval_data = {
            "sample_id": "TestApp",
            "platforms": {
                "android": {
                    "build_status": "success",
                    "install_status": "success",
                    "launch_status": "success",
                    "stability_metrics": {
                        "crash_count": 0,
                        "anr_count": 1,
                        "white_screen_count": 0,
                    },
                    "test_results": [
                        {"test_case_id": "TC001", "passed": True},
                    ],
                },
            },
        }
        write_evaluation(workspace, "TestApp", eval_data)

        consolidate_sample_report(workspace, "TestApp")

        report = json.loads((workspace / "TestApp" / "sample_report.json").read_text())
        plat = report["platforms"]["android"]
        assert plat["build_status"] == "success"
        assert plat["crash_count"] == 0
        assert plat["anr_count"] == 1
        assert plat["white_screen_count"] == 0
        assert "e2e_test_cases" in plat
        # 派生字段
        assert plat["generation_success"] is True
        assert plat["install_success"] is True
        assert plat["launch_success"] is True
        assert plat["is_deliverable"] is True

    def test_consolidate_evaluation_failed_status(self, workspace):
        """evaluation.json 中 launch_status=failed 时派生字段正确。"""
        gen_data = {"sample_id": "TestApp", "generator": "custom_gen"}
        write_generation(workspace, "TestApp", gen_data)

        eval_data = {
            "sample_id": "TestApp",
            "platforms": {
                "ios": {
                    "build_status": "success",
                    "install_status": "success",
                    "launch_status": "failed",
                    "stability_metrics": {},
                    "test_results": [],
                },
            },
        }
        write_evaluation(workspace, "TestApp", eval_data)

        consolidate_sample_report(workspace, "TestApp")
        report = json.loads((workspace / "TestApp" / "sample_report.json").read_text())
        plat = report["platforms"]["ios"]
        assert plat["generation_success"] is True
        assert plat["install_success"] is True
        assert plat["launch_success"] is False
        assert plat["is_deliverable"] is False

    def test_consolidate_both_scores_and_evaluation(self, workspace):
        """同时合并 scores.json 和 evaluation.json，数据不冲突。"""
        gen_data = {"sample_id": "TestApp", "generator": "custom_gen", "duration_ms": 50000}
        write_generation(workspace, "TestApp", gen_data)

        scores_data = {
            "sample_id": "TestApp",
            "platforms": {
                "android": {
                    "success_rate_score": 90.0,
                    "quality_score": 85.0,
                    "experience_score": 80.0,
                    "stability_score": 95.0,
                    "launch_screenshot": "",
                    "requires_backend": True,
                    "backend_completeness": 0.6,
                },
            },
        }
        write_scores(workspace, "TestApp", scores_data)

        eval_data = {
            "sample_id": "TestApp",
            "platforms": {
                "android": {
                    "build_status": "success",
                    "install_status": "success",
                    "launch_status": "success",
                    "stability_metrics": {"crash_count": 0, "anr_count": 0, "white_screen_count": 0},
                    "test_results": [{"test_case_id": "TC001", "passed": True}],
                },
            },
        }
        write_evaluation(workspace, "TestApp", eval_data)

        consolidate_sample_report(workspace, "TestApp")
        report = json.loads((workspace / "TestApp" / "sample_report.json").read_text())

        plat = report["platforms"]["android"]
        # 来自 scores.json
        assert plat["success_rate_score"] == 90.0
        assert plat["backend_completeness"] == 0.6
        # 来自 evaluation.json
        assert plat["build_status"] == "success"
        assert plat["crash_count"] == 0
        assert "e2e_test_cases" in plat
        # 派生字段
        assert plat["is_deliverable"] is True

    def test_consolidate_preserves_existing_platform_data(self, workspace):
        """已有 sample_report.json 中的 platforms 数据不被覆盖。"""
        existing_report = {
            "sample_id": "TestApp",
            "generator": "custom_gen",
            "duration_ms": 50000,
            "platforms": {
                "android": {
                    "custom_field": "should_remain",
                    "success_rate_score": 99.0,
                },
            },
        }
        _write_json(workspace / "TestApp" / "sample_report.json", existing_report)

        scores_data = {
            "sample_id": "TestApp",
            "platforms": {
                "android": {
                    "success_rate_score": 80.0,  # 低于已有值
                    "quality_score": 75.0,
                },
            },
        }
        write_scores(workspace, "TestApp", scores_data)

        consolidate_sample_report(workspace, "TestApp")
        report = json.loads((workspace / "TestApp" / "sample_report.json").read_text())

        plat = report["platforms"]["android"]
        # 自定义字段保留
        assert plat["custom_field"] == "should_remain"
        # scores.json 的评分字段始终覆盖已有值
        assert plat["success_rate_score"] == 80.0
        # 新字段被添加
        assert plat["quality_score"] == 75.0

    def test_consolidate_idempotent(self, workspace):
        """多次调用 consolidate 结果一致。"""
        gen_data = {"sample_id": "TestApp", "generator": "custom_gen", "duration_ms": 50000}
        write_generation(workspace, "TestApp", gen_data)

        consolidate_sample_report(workspace, "TestApp")
        report1 = json.loads((workspace / "TestApp" / "sample_report.json").read_text())

        consolidate_sample_report(workspace, "TestApp")
        report2 = json.loads((workspace / "TestApp" / "sample_report.json").read_text())

        # evaluated_at 会变化，其余字段应一致
        assert report1["sample_id"] == report2["sample_id"]
        assert report1["duration_ms"] == report2["duration_ms"]
        # evaluated_at 因时间差异可能不同
        assert "evaluated_at" in report2

    def test_consolidate_all_skips_non_sample_dirs(self, workspace):
        """consolidate_all_sample_reports 跳过已知非样本目录。"""
        # 创建一个非样本目录
        (workspace / "e2e_reports").mkdir()
        (workspace / "e2e_reports" / "dummy.json").write_text("{}", encoding="utf-8")

        # 创建一个有效样本
        gen_data = {"sample_id": "TestApp", "generator": "custom_gen"}
        write_generation(workspace, "TestApp", gen_data)

        consolidate_all_sample_reports(workspace)

        # e2e_reports 下不应生成 sample_report.json
        assert not (workspace / "e2e_reports" / "sample_report.json").exists()
        # TestApp 下应有
        assert (workspace / "TestApp" / "sample_report.json").exists()

    def test_consolidate_handles_missing_files(self, workspace):
        """没有任何数据文件时不崩溃，创建最小报告。"""
        (workspace / "EmptySample").mkdir()

        consolidate_sample_report(workspace, "EmptySample")

        report_path = workspace / "EmptySample" / "sample_report.json"
        assert report_path.exists()
        report = json.loads(report_path.read_text())
        assert report["sample_id"] == "EmptySample"

    def test_consolidate_null_fields_for_backward_compat(self, workspace):
        """缺失字段填充 null 保持向后兼容。"""
        gen_data = {"sample_id": "TestApp", "generator": "custom_gen"}
        write_generation(workspace, "TestApp", gen_data)

        consolidate_sample_report(workspace, "TestApp")
        report = json.loads((workspace / "TestApp" / "sample_report.json").read_text())

        for key in ("sample_title", "complexity", "top_category", "error_message",
                    "functionality_score", "success_rate_reason",
                    "usecase_reason", "stability_reason",
                    "duration_reason", "package_size_reason"):
            assert key in report, f"Missing key: {key}"
            assert report[key] is None, f"Expected null for {key}, got {report[key]}"

    def test_consolidate_stability_logs_detection(self, workspace):
        """检测 stability_logs 目录并设置 has_stability_logs。"""
        gen_data = {"sample_id": "TestApp", "generator": "custom_gen"}
        write_generation(workspace, "TestApp", gen_data)

        eval_data = {
            "sample_id": "TestApp",
            "platforms": {
                "android": {
                    "build_status": "success",
                    "install_status": "success",
                    "launch_status": "success",
                    "stability_metrics": {},
                    "test_results": [],
                },
            },
        }
        write_evaluation(workspace, "TestApp", eval_data)

        # 创建 stability_logs 目录
        stab_dir = workspace / "TestApp" / "stability_logs" / "custom_gen"
        stab_dir.mkdir(parents=True)
        (stab_dir / "crash_anr_events.json").write_text(
            json.dumps({"platform": "android", "crash_count": 0}),
            encoding="utf-8",
        )

        consolidate_sample_report(workspace, "TestApp")
        report = json.loads((workspace / "TestApp" / "sample_report.json").read_text())

        plat = report["platforms"]["android"]
        assert plat["has_stability_logs"] is True
        assert plat["stability_log_path"] is not None
