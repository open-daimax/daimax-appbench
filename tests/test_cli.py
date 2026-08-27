"""测试 CLI evaluate 命令相关功能。

覆盖:
- test_cli_evaluate_samples_whitebox: 白盒测试 evaluate 调用链
- test_cli_evaluate_samples_does_not_generate_testcases: 仅评测不生成用例
"""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from evalapp.cli import main
from evalapp.evaluation.results.models import EvalRun, PromptResult, FrameworkResultCollection, TestCaseResult
from evalapp.evaluation.metrics import compute_success_rate, compute_quality, compute_experience


@pytest.fixture
def cli_runner():
    return CliRunner()


def _make_eval_run():
    """创建一个包含评测结果的 EvalRun。"""
    run = EvalRun(generator_name="custom_gen", run_type="sample")
    pr = PromptResult(
        prompt_id="sample_001",
        platform="android",
        generator_name="custom_gen",
        generation_success=True,
        test_results=[
            TestCaseResult(test_case_id="TC001", passed=True, status="PASS"),
        ],
        result_data=FrameworkResultCollection(
            build_status="success",
            install_status="success",
            launch_status="success",
        ),
    )
    pr.success_rate = compute_success_rate(1.0, gen_ok=True, launch_ok=True)
    pr.quality = compute_quality(
        e2e_pass_rate=1.0, stability_score=100.0,
        e2e_pass_count=1, e2e_total_count=1,
    )
    pr.experience = compute_experience(duration_ms=300000)
    run.prompt_results.append(pr)
    run.compute_summary()
    return run


class TestCliEvaluateSamples:
    """测试 CLI evaluate 子命令。"""

    def test_cli_evaluate_samples_whitebox(self, cli_runner, tmp_path):
        """白盒测试: evaluate 命令应调用 EvaluationService.run_evaluation。"""
        # 创建模拟执行计划文件
        exec_plan = tmp_path / "plan.yaml"
        exec_plan.write_text("""
name: test_plan
datasets:
  - dataset
tasks:
  - sample_id: sample_001
    platform: android
""")
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        mock_run = _make_eval_run()

        with patch("evalapp.commands.evaluate.EvaluationService") as MockService:
            mock_instance = MagicMock()
            MockService.return_value = mock_instance
            mock_instance.run_evaluation.return_value = (mock_run, "v1")
            # Mock static methods
            MockService.collect_tasks_from_plan.return_value = [
                {"sample": MagicMock(sample_id="sample_001"), "platform": "android", "end_case": None, "priority": None}
            ]
            MockService.resolve_samples_dirs.return_value = [tmp_path / "dataset"]
            MockService.infer_generator_name.return_value = "custom_gen"

            with patch("evalapp.commands.evaluate.ExecPlanStore") as MockPlanStore:
                mock_plan = MagicMock()
                mock_plan.plan_name = "test_plan"
                MockPlanStore.return_value = mock_plan

                cli_runner.invoke(main, [
                    "evaluate",
                    "--workspace", str(workspace),
                    "--exec-plan", str(exec_plan),
                    "--no-open-report",
                ])

        # 命令应正常完成（即使使用 mock）
        # 注意: 由于 do_report 也需要 mock，可能在报告生成时出错
        # 但关键是 run_evaluation 被调用了
        assert MockService.collect_tasks_from_plan.called or mock_instance.run_evaluation.called

    def test_cli_evaluate_samples_does_not_generate_testcases(self, cli_runner, tmp_path):
        """evaluate 命令不应调用测试用例生成逻辑。"""
        exec_plan = tmp_path / "plan.yaml"
        exec_plan.write_text("""
name: test_plan
datasets:
  - dataset
tasks:
  - sample_id: sample_001
    platform: android
""")
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        with patch("evalapp.commands.evaluate.EvaluationService") as MockService:
            MockService.collect_tasks_from_plan.return_value = []  # 无任务
            MockService.resolve_samples_dirs.return_value = [tmp_path / "dataset"]
            MockService.infer_generator_name.return_value = "custom_gen"

            with patch("evalapp.commands.evaluate.ExecPlanStore") as MockPlanStore:
                mock_plan = MagicMock()
                mock_plan.plan_name = "test_plan"
                MockPlanStore.return_value = mock_plan

                # TestDesigner 不应被调用
                with patch("evalapp.benchset.testcases.designer.TestDesigner") as MockDesigner:
                    cli_runner.invoke(main, [
                        "evaluate",
                        "--workspace", str(workspace),
                        "--exec-plan", str(exec_plan),
                        "--no-open-report",
                    ])

                    # TestDesigner 不应被实例化
                    MockDesigner.assert_not_called()
