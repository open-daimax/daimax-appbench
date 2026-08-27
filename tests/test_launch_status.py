"""Tests for launch status inference and white-screen gating (修复二).

Covers the design intent "launch failure *or* white screen after launch ->
success rate 0", honouring the zero-false-positive red line: only a
definitive ``verifications.white_screen.detected == True`` may zero the
rate; missing / empty / non-dict fields must never be misjudged.
"""

from __future__ import annotations

import pytest

from evalapp.evaluation.results.models import (
    FrameworkResultCollection,
    ProcessCollection,
    PromptResult,
    TestCaseResult,
)
from evalapp.evaluation.runner.test_phase import infer_launch_status
from evalapp.evaluation.runner.validators import compute_success_rate


def _tc_result(
    *,
    tc_id: str = "TC_LAUNCH",
    passed: bool = True,
    verifications: dict | None = None,
) -> TestCaseResult:
    return TestCaseResult(
        test_case_id=tc_id,
        passed=passed,
        status="PASS" if passed else "FAIL",
        verifications=verifications,
    )


def _make_prompt_result(*, launch_status: str) -> PromptResult:
    """Build a minimal PromptResult with the given launch_status."""
    return PromptResult(
        prompt_id="sample_001",
        platform="ios",
        generator_name="test",
        generation_success=True,
        process_data=ProcessCollection(),
        result_data=FrameworkResultCollection(
            build_status="success",
            install_status="success",
            launch_status=launch_status,
        ),
    )


class TestInferLaunchStatus:
    """infer_launch_status 行为测试。"""

    def test_no_results_returns_unknown(self):
        assert infer_launch_status([]) == "unknown"

    def test_tc_launch_failed(self):
        # TC_LAUNCH 失败（超时/异常/断言失败）→ 启动失败
        results = [_tc_result(passed=False)]
        assert infer_launch_status(results) == "failed"

    def test_tc_launch_passed_no_white_screen(self):
        results = [_tc_result(passed=True, verifications=None)]
        assert infer_launch_status(results) == "success"

    def test_tc_launch_passed_with_white_screen_detected(self):
        # c) TC_LAUNCH 通过但白屏 detected=true → 启动失败（启动后白屏）
        results = [
            _tc_result(
                passed=True,
                verifications={"white_screen": {"detected": True}},
            )
        ]
        assert infer_launch_status(results) == "failed"

    @pytest.mark.parametrize(
        "verifications",
        [
            None,  # verifications 缺失
            {},  # 空字典
            {"white_screen": None},  # white_screen 为 None
            {"white_screen": {}},  # white_screen 空字典
            {"white_screen": {"detected": False}},  # 明确 false
            {"white_screen": {"detected": None}},  # detected 为 None
            {"white_screen": "not-a-dict"},  # white_screen 非 dict
            {"other": {"detected": True}},  # 其它验项不相关
        ],
    )
    def test_white_screen_missing_field_not_misjudged(self, verifications):
        # d) 白屏字段缺失/为空时不得误判为白屏（零误报红线）
        results = [_tc_result(passed=True, verifications=verifications)]
        assert infer_launch_status(results) == "success"

    def test_no_tc_launch_some_passed(self):
        # 无 TC_LAUNCH 时，任一用例通过即视为启动成功
        results = [
            _tc_result(tc_id="TC001", passed=True),
            _tc_result(tc_id="TC002", passed=False),
        ]
        assert infer_launch_status(results) == "success"

    def test_no_tc_launch_all_failed(self):
        results = [_tc_result(tc_id="TC001", passed=False)]
        assert infer_launch_status(results) == "failed"


class TestWhiteScreenGatesSuccessRate:
    """白屏/启动失败回写成功率端到端验证。"""

    def test_launch_failed_drives_success_rate_to_zero(self):
        # c) launch_status="failed" → compute_success_rate 首次成功率为 0
        pr = _make_prompt_result(launch_status="failed")
        metrics = compute_success_rate(pr)
        assert metrics.initial_generation_rate == 0.0

    def test_launch_success_keeps_success_rate(self):
        pr = _make_prompt_result(launch_status="success")
        metrics = compute_success_rate(pr)
        assert metrics.initial_generation_rate == 100.0

    def test_white_screen_gates_success_rate_end_to_end(self):
        # c) 端到端：TC_LAUNCH 通过但白屏 detected=true ->
        #    infer_launch_status="failed" -> compute_success_rate 为 0
        results = [
            _tc_result(
                passed=True,
                verifications={"white_screen": {"detected": True}},
            )
        ]
        launch_status = infer_launch_status(results)
        assert launch_status == "failed"
        pr = _make_prompt_result(launch_status=launch_status)
        metrics = compute_success_rate(pr)
        assert metrics.initial_generation_rate == 0.0
