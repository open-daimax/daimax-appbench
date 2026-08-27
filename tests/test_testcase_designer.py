"""Tests for test case designer parsing behavior."""

import tempfile
from pathlib import Path

from evalapp.benchset.samples.models import EvalPrompt
from evalapp.benchset.testcases.designer import TestDesigner, _repair_jsonish_text


def _make_designer() -> TestDesigner:
    # 解析类测试不触发 Agent CLI 调用，注入 None 即可（开源版 runner 可注入）
    return TestDesigner(None, Path("test_cases"))


def test_extract_nested_test_suite_test_cases():
    designer = _make_designer()
    data = {
        "test_strategy": {"test_type": "e2e_ui"},
        "test_suite": {
            "name": "计算器测试",
            "test_cases": [
                {
                    "id": "TC001",
                    "name": "加法计算",
                    "description": "验证基础加法",
                    "steps": [
                        {"step": 1, "action": "输入 1+2=", "expected": "显示 3"},
                    ],
                }
            ],
        },
    }

    items = designer._extract_test_case_items(data)

    assert len(items) == 1
    assert items[0]["id"] == "TC001"


def test_parse_raw_output_with_nested_test_suite():
    designer = _make_designer()
    raw_output = """
说明文字
{
  "test_strategy": {"test_type": "e2e_ui"},
  "test_suite": {
    "name": "计算器测试",
    "test_cases": [
      {
        "id": "TC001",
        "name": "加法计算",
        "description": "验证基础加法",
        "steps": [
          {"step": 1, "action": "输入 1+2=", "expected": "显示 3"}
        ]
      }
    ]
  }
}
"""

    cases = designer._parse_from_raw_output(raw_output)

    assert len(cases) == 1
    assert cases[0].id == "TC001"
    assert cases[0].steps == ["输入 1+2= -> 预期: 显示 3"]


def test_parse_raw_output_with_nested_wrappers_and_variant_keys():
    designer = _make_designer()
    raw_output = """
分析说明
```json
{
  "deliverables": {
    "ui_suite": {
      "cases": [
        {
          "case_id": "TC002",
          "scenario": "新增待办项",
          "summary": "验证用户可以新增一条待办",
          "test_steps": [
            {
              "step": "输入待办内容并点击添加",
              "expected_outcome": "列表中出现新的待办项"
            }
          ],
          "expected_results": [
            "待办项被成功创建",
            "输入框被清空"
          ]
        }
      ]
    }
  }
}
```
"""

    cases = designer._parse_from_raw_output(raw_output)

    assert len(cases) == 1
    assert cases[0].id == "TC002"
    assert cases[0].name == "新增待办项"
    assert cases[0].description == "验证用户可以新增一条待办"
    assert cases[0].steps == ["输入待办内容并点击添加 -> 预期: 列表中出现新的待办项"]
    assert cases[0].expected_result == "待办项被成功创建；输入框被清空"


def test_parse_raw_output_aggregates_multiple_cases_from_malformed_suite():
    designer = _make_designer()
    raw_output = """
{
  "test_strategy": {"test_type": "e2e_ui"},
  "test_suite": {
    "test_cases": [
      {
        "id": "TC001",
        "name": "首页展示",
        "description": "验证首页商户列表",
        "priority": "P0",
        "steps": [
          {"step": 1, "action": "打开首页", "expected": "列表正常显示"}
        ],
        "expected_result": "首页显示正常"
      },
      {
        "id": "TC002",
        "name": "加入购物车",
        "description": "验证加入购物车",
        "priority": "P0",
        "steps": [
          {"step": 1, "action": "点击加号", "expected": "数量显示为"1""}
        ],
        "expected_result": "购物车数量更新"
      }
    ]
  }
}
"""

    cases = designer._parse_from_raw_output(raw_output)

    assert len(cases) == 2
    assert [case.id for case in cases] == ["TC001", "TC002"]
    assert cases[1].steps == ['点击加号 -> 预期: 数量显示为"1"']


def test_repair_jsonish_text_escapes_inner_quotes():
    repaired = _repair_jsonish_text(
        '{"action":"输入"北京"","expected":"城市切换为"北京""}'
    )

    assert '\\"北京\\"' in repaired


def test_build_prompt_requests_direct_json_without_file_write():
    designer = _make_designer()
    prompt = EvalPrompt(id="S002", text="实现一个待办事项应用", platforms=["android"])

    content = designer._build_prompt(prompt, "android")

    assert "不要请求任何文件写入" in content
    assert "只返回 JSON" not in content
    assert "test_intermediates/test_design_output/test_cases.json" not in content


def test_design_tests_removes_test_intermediates_after_parse():
    class FakeResult:
        success = True
        output = """
{
  "test_strategy": {"test_type": "e2e_ui"},
  "test_suite": {
    "test_cases": [
      {
        "id": "TC001",
        "name": "加法计算",
        "description": "验证基础加法"
      }
    ]
  }
}
"""
        error = ""

    class FakeClaudeClient:
        def run(self, **kwargs):
            return FakeResult()

    with tempfile.TemporaryDirectory() as tmpdir:
        designer = TestDesigner(FakeClaudeClient(), Path(tmpdir))
        prompt = EvalPrompt(id="S001", text="实现一个计算器应用", platforms=["android"])

        output = designer.design_tests(prompt, "android")
        work_dir = Path(tmpdir) / "S001" / "android"

        assert len(output.test_cases) == 1
        assert not (work_dir / "test_intermediates").exists()


def test_design_tests_retries_with_strict_json_prompt_after_non_json_output():
    class FakeResult:
        def __init__(self, output: str, success: bool = True, error: str = ""):
            self.success = success
            self.output = output
            self.error = error

    class FakeClaudeClient:
        def __init__(self):
            self.prompts: list[str] = []
            self.calls = 0

        def run(self, **kwargs):
            self.prompts.append(kwargs["prompt"])
            self.calls += 1
            if self.calls == 1:
                return FakeResult(
                    "文件写入需要您授权。以下是测试策略和测试用例列表（Markdown 表格）"
                )
            return FakeResult(
                """
{
  "test_strategy": {"test_type": "e2e_ui", "reasoning": "纯 UI 交互", "risk_level": "high"},
  "test_suite": {
    "name": "待办事项应用测试",
    "description": "验证待办事项核心流程",
    "test_cases": [
      {
        "id": "TC001",
        "name": "新增待办项",
        "description": "验证新增待办项",
        "priority": "P0",
        "steps": [
          {"step": 1, "action": "输入待办内容并点击添加", "expected": "列表中出现新的待办项"}
        ],
        "expected_result": "成功新增一条待办项"
      }
    ]
  }
}
"""
            )

    with tempfile.TemporaryDirectory() as tmpdir:
        client = FakeClaudeClient()
        designer = TestDesigner(client, Path(tmpdir))
        prompt = EvalPrompt(id="S002", text="实现一个待办事项应用", platforms=["android"])

        output = designer.design_tests(prompt, "android")

        assert client.calls == 2
        assert "不要请求任何文件写入" in client.prompts[0]
        assert "不要请求文件写入，不要请求任何授权" in client.prompts[1]
        assert len(output.test_cases) == 1
        assert output.test_cases[0].id == "TC001"
        assert "retry-attempt-output" in output.raw_output


def test_design_tests_preserves_intermediates_when_parse_fails():
    class FakeResult:
        success = True
        output = "模型只输出了说明，没有结构化 JSON"
        error = ""

    class FakeClaudeClient:
        def run(self, **kwargs):
            return FakeResult()

    with tempfile.TemporaryDirectory() as tmpdir:
        designer = TestDesigner(FakeClaudeClient(), Path(tmpdir))
        prompt = EvalPrompt(id="S002", text="实现一个待办事项应用", platforms=["android"])
        work_dir = Path(tmpdir) / "S002" / "android"

        output = designer.design_tests(prompt, "android")

        assert output.test_cases == []
        assert "retry-attempt-output" in output.raw_output
        assert (work_dir / "test_intermediates").exists()
