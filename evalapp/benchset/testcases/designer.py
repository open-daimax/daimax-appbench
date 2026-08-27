"""TestDesigner: generates test cases via an injectable agent CLI runner.

评测仓本身不内置任何 Agent CLI 实现：用例设计所需的生成能力由
外部包（如 daimax-appbench-gen / evalgen）提供，并通过构造函数注入
符合 :class:`AgentRunner` 协议的客户端。未注入时调用
:meth:`TestDesigner.design_tests` 会给出清晰的安装指引错误。
"""

from __future__ import annotations

import json
import re
import shutil
import uuid
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from ..samples.models import EvalPrompt
from ...utils.logging import get_logger
from .models import TestCase, TestDesignOutput

logger = get_logger(__name__)


class GenerationCapabilityNotInjectedError(RuntimeError):
    """用例设计需要外部注入的生成能力，但当前未注入。"""

    def __init__(self) -> None:
        super().__init__(
            "测试用例设计需要 Agent CLI 生成能力，当前未注入。"
            "请安装 evalgen（daimax-appbench-gen）并注入其生成能力："
            "TestDesigner(agent_runner=<实现了 AgentRunner 协议的客户端>, ...)"
        )


@runtime_checkable
class AgentRunner(Protocol):
    """用例设计所需的 Agent CLI 运行器协议（由生成侧插件实现）。

    与原 ClaudeCLIClient.run 的调用契约保持一致：返回对象需含
    ``success``、``output``、``error``、``duration``、``session_id``、
    ``raw_events`` 属性。
    """

    def run(
        self,
        prompt: str,
        work_dir: str,
        session_id: str,
    ) -> Any: ...


class TestDesigner:
    """Generates test cases for a given prompt using a self-contained design prompt."""

    def __init__(self, agent_runner: AgentRunner | None, test_cases_dir: Path) -> None:
        self.claude_client = agent_runner  # 兼容旧属性名：实际为注入的 AgentRunner
        self.test_cases_dir = test_cases_dir

    def design_tests(self, prompt: EvalPrompt, platform: str) -> TestDesignOutput:
        """Generate test cases for a prompt on a given platform.

        Creates a working directory, invokes the injected agent runner with a
        self-contained test-design prompt, then parses the output into
        structured test cases.
        """
        if self.claude_client is None:
            raise GenerationCapabilityNotInjectedError()
        work_dir = self.test_cases_dir / prompt.id / platform
        work_dir.mkdir(parents=True, exist_ok=True)
        intermediates_dir = work_dir / "test_intermediates" / "test_design_output"
        intermediates_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"Designing tests for {prompt.id}/{platform}...")

        raw_outputs: list[str] = []
        result = self._run_attempt(
            work_dir=work_dir,
            prompt_text=self._build_prompt(prompt, platform),
        )
        raw_outputs.append(result.error if not result.success else result.output)

        if not result.success:
            logger.error(f"Test design failed for {prompt.id}/{platform}: {result.error}")
            logger.error(f"  Duration: {result.duration:.2f}s")
            logger.error(f"  Session ID: {result.session_id}")
            logger.error(f"  Raw events count: {len(result.raw_events)}")
            
            # Save detailed error to file for debugging
            error_log_path = work_dir / "error_details.txt"
            with open(error_log_path, 'w') as f:
                f.write("=== Test Design Failure Details ===\n")
                f.write(f"Sample: {prompt.id}\n")
                f.write(f"Platform: {platform}\n")
                f.write(f"Duration: {result.duration:.2f}s\n")
                f.write(f"Error: {result.error}\n")
                f.write("\n=== Raw Output (first 2000 chars) ===\n")
                f.write(result.output[:2000])
                f.write("\n\n=== Raw Events (first 5) ===\n")
                for i, event in enumerate(result.raw_events[:5]):
                    f.write(f"\nEvent {i}: {json.dumps(event, ensure_ascii=False)[:500]}\n")
            logger.error(f"  Error details saved to: {error_log_path}")
            
            return TestDesignOutput(
                prompt_id=prompt.id,
                platform=platform,
                raw_output=self._join_raw_outputs(raw_outputs),
            )

        # Parse test cases from the output and intermediate files
        test_cases = self._parse_test_cases(work_dir, result.output)
        if not test_cases:
            logger.warning(
                "No test cases parsed for %s/%s on first attempt; retrying with strict JSON-only prompt",
                prompt.id,
                platform,
            )
            retry_result = self._run_attempt(
                work_dir=work_dir,
                prompt_text=self._build_retry_prompt(prompt, platform, result.output),
            )
            raw_outputs.append(
                retry_result.error if not retry_result.success else retry_result.output
            )
            if retry_result.success:
                test_cases = self._parse_test_cases(work_dir, retry_result.output)

        if test_cases:
            self._cleanup_intermediates(work_dir)
        else:
            logger.warning(
                "No test cases parsed for %s/%s after retry; preserving intermediates for debugging",
                prompt.id,
                platform,
            )

        output = TestDesignOutput(
            prompt_id=prompt.id,
            platform=platform,
            test_cases=test_cases,
            raw_output=self._join_raw_outputs(raw_outputs),
        )

        logger.info(
            f"Generated {len(test_cases)} test cases for {prompt.id}/{platform}"
        )
        return output

    def _build_prompt(self, prompt: EvalPrompt, platform: str) -> str:
        """Build the self-contained Claude prompt for test-case design."""
        base_prompt = (
            f"你是资深移动应用测试设计专家，请为以下应用需求设计E2E UI测试用例。\n\n"
            f"应用需求描述：\n{prompt.text}\n\n"
            f"目标平台：{platform}\n\n"
            f"这是一个待生成的移动应用，请选择 e2e_ui 作为测试类型，"
            f"为该应用设计全面的E2E UI测试用例，涵盖所有核心功能。\n"
            f"不要分析当前仓库代码，也不要生成集成测试。\n"
            f"不要请求任何文件写入、工具授权或额外权限。\n"
            f"请直接在最终回复中输出一个合法 JSON 对象，不要输出 Markdown、代码块、表格或解释文字。\n\n"
            f"返回 JSON 必须使用以下结构：\n"
            "{\n"
            '  "test_strategy": {\n'
            '    "test_type": "e2e_ui",\n'
            '    "reasoning": "string",\n'
            '    "risk_level": "low|medium|high"\n'
            "  },\n"
            '  "test_suite": {\n'
            '    "name": "string",\n'
            '    "description": "string",\n'
            '    "test_cases": [\n'
            "      {\n"
            '        "id": "TC001",\n'
            '        "name": "string",\n'
            '        "description": "string",\n'
            '        "priority": "P0|P1|P2",\n'
            '        "steps": [\n'
            '          {"step": 1, "action": "string", "expected": "string"}\n'
            "        ],\n"
            '        "expected_result": "string",\n'
            '        "tags": ["string"]\n'
            "      }\n"
            "    ]\n"
            "  }\n"
            "}"
        )

        base_prompt += (
            "\n\n测试用例设计要求：\n"
            "1. 按页面维度设计用例：requirement中每个【页面】的核心功能都必须有对应测试用例覆盖\n"
            "2. 页面间导航必须覆盖：凡是存在'点击→进入子页面'的跳转关系，需有专门用例验证该跳转及子页面内容\n"
            "3. 用例数量与页面/功能数成正比：每个页面至少2-3个用例覆盖其主要交互功能\n"
            "4. 优先级分配：核心交互流程P0，重要辅助功能P1，边缘状态/空状态P2\n"
        )

        # 添加约束条件信息
        if prompt.constraints:
            constraints_text = "\n\n约束条件（测试用例必须遵守）：\n"
            for c in prompt.constraints:
                constraints_text += f"- {c}\n"
            base_prompt += constraints_text
        
        # 添加游戏分类信息
        if prompt.game_category:
            base_prompt += f"\n游戏类型：{prompt.game_category}，请根据该类型的特点设计针对性测试用例。\n"
        
        # 添加补充说明
        if prompt.notes:
            base_prompt += f"\n测试重点说明：{prompt.notes}\n"
        
        # 添加后端服务和认证相关的测试要求
        if prompt.requires_backend or prompt.requires_auth:
            backend_requirements = "\n\n特殊要求：\n"
            if prompt.requires_backend:
                backend_requirements += "- 该应用需要后端服务支持，请设计相关的网络请求和数据同步测试用例\n"
            if prompt.requires_auth:
                if platform == "miniprogram":
                    backend_requirements += (
                        "- 该应用需要用户认证（登录/注册），小程序测试用例必须遵守：\n"
                        "  1. TC001必须是注册登录用例；小程序登录可能通过一键登录、微信登录、授权登录等方式完成，不一定存在邮箱/密码输入框，请使用页面提供的登录入口完成登录\n"
                        "  2. 其他所有功能用例的第一步必须包含登录前置条件：'如果当前显示登录页面，使用页面提供的登录方式完成登录后继续'\n"
                        "  3. 最后一个用例应包含退出登录功能验证\n"
                        "  4. 不要设计密码找回、验证码登录等非核心认证用例\n"
                    )
                else:
                    backend_requirements += (
                        "- 该应用需要用户认证（登录/注册），测试用例必须遵守：\n"
                        "  1. TC001必须是注册登录用例，使用标准测试账号：邮箱123@qq.com，密码12345678\n"
                        "  2. 其他所有功能用例的第一步必须包含登录前置条件：'如果当前显示登录页面，使用邮箱123@qq.com密码12345678登录后继续'\n"
                        "  3. 最后一个用例应包含退出登录功能验证\n"
                        "  4. 不要设计密码找回、第三方登录、验证码登录等非核心认证用例\n"
                    )
            base_prompt += backend_requirements
        
        return base_prompt

    def _build_retry_prompt(
        self,
        prompt: EvalPrompt,
        platform: str,
        previous_output: str,
    ) -> str:
        """Build a stricter retry prompt when the first attempt is not parseable."""
        return (
            f"重新生成 {prompt.id}/{platform} 的 E2E UI 测试用例。\n\n"
            f"应用需求描述：\n{prompt.text}\n\n"
            f"上一次回复未返回可解析 JSON，原始回复如下：\n{previous_output[:4000]}\n\n"
            "这次请严格遵守以下要求：\n"
            "1. 不要请求文件写入，不要请求任何授权，不要调用会触发授权的操作。\n"
            "2. 不要输出分析、说明、Markdown、代码块、表格。\n"
            "3. 回复内容必须是一个合法 JSON 对象，且首字符是 {，末字符是 }。\n"
            '4. 顶层必须包含 "test_strategy" 和 "test_suite.test_cases"。\n'
            '5. "test_suite.test_cases" 必须是非空数组，每个用例都要包含 id、name、description、priority、steps。\n'
            '6. "test_strategy.test_type" 必须是 "e2e_ui"。\n'
            "现在只返回 JSON。"
        )

    def _run_attempt(self, work_dir: Path, prompt_text: str):
        """Execute one test-design attempt via the injected agent runner."""
        return self.claude_client.run(
            prompt=prompt_text,
            work_dir=str(work_dir),
            session_id=str(uuid.uuid4()),
        )

    def _join_raw_outputs(self, outputs: list[str]) -> str:
        """Join multiple attempt outputs for later debugging."""
        cleaned = [output.strip() for output in outputs if output and output.strip()]
        if not cleaned:
            return ""
        if len(cleaned) == 1:
            return cleaned[0]
        return "\n\n=== retry-attempt-output ===\n\n".join(cleaned)

    def _parse_test_cases(self, work_dir: Path, raw_output: str) -> list[TestCase]:
        """Parse test cases from test-design output.

        Tries to read from test_intermediates/test_design_output/ first,
        then falls back to parsing the raw CLI output.
        """
        # Try reading from intermediate files
        intermediates_dir = work_dir / "test_intermediates" / "test_design_output"
        if intermediates_dir.exists():
            test_cases = self._parse_from_intermediates(intermediates_dir)
            if test_cases:
                return test_cases

        # Fallback: parse from raw output
        return self._parse_from_raw_output(raw_output)

    def _parse_from_intermediates(self, intermediates_dir: Path) -> list[TestCase]:
        """Parse test cases from intermediate files generated during test design."""
        test_cases: list[TestCase] = []
        for json_file in intermediates_dir.glob("*.json"):
            try:
                with open(json_file) as f:
                    data = json.load(f)
                test_cases.extend(self._items_to_test_cases(data))
            except (json.JSONDecodeError, KeyError):
                continue
        return test_cases

    def _parse_from_raw_output(self, raw_output: str) -> list[TestCase]:
        """Best-effort parse test cases from raw CLI text output."""
        aggregated: list[TestCase] = []
        structural_blocks = sorted(
            _find_structural_json_blocks(raw_output),
            key=len,
            reverse=True,
        )
        for payload in structural_blocks:
            repaired = _repair_jsonish_text(payload)
            try:
                data = json.loads(repaired)
                aggregated = self._merge_test_cases(
                    aggregated,
                    self._items_to_test_cases(data),
                )
            except json.JSONDecodeError:
                continue

        for payload in _find_json_blocks(raw_output):
            try:
                data = json.loads(payload)
                aggregated = self._merge_test_cases(
                    aggregated,
                    self._items_to_test_cases(data),
                )
            except json.JSONDecodeError:
                continue

        # If the top-level JSON is malformed, fall back to extracting each testcase
        # fragment from the raw text and recover fields line-by-line.
        aggregated = self._merge_test_cases(
            aggregated,
            self._parse_test_cases_from_text(raw_output),
        )
        return aggregated

    def _extract_test_case_items(self, data: object) -> list[dict]:
        """Extract test case item dicts from common and nested output shapes."""
        items = self._collect_test_case_items(data)
        deduped: list[dict] = []
        seen: set[str] = set()
        for item in items:
            item_key = str(
                item.get("id")
                or item.get("test_id")
                or item.get("case_id")
                or json.dumps(item, sort_keys=True, ensure_ascii=False)
            )
            if item_key in seen:
                continue
            seen.add(item_key)
            deduped.append(item)
        return deduped

    def _collect_test_case_items(self, data: object) -> list[dict]:
        """Recursively collect testcase-like dicts from nested payloads."""
        if isinstance(data, str):
            stripped = data.strip()
            if stripped.startswith(("{", "[")):
                try:
                    return self._collect_test_case_items(json.loads(stripped))
                except json.JSONDecodeError:
                    return []
            return []

        if isinstance(data, list):
            items: list[dict] = []
            for value in data:
                items.extend(self._collect_test_case_items(value))
            return items

        if not isinstance(data, dict):
            return []

        if self._is_test_case_dict(data):
            return [data]

        items: list[dict] = []
        preferred_keys = (
            "test_cases",
            "testCases",
            "cases",
            "test_suite",
            "testSuite",
            "e2e_ui",
            "integration_test",
            "mixed",
            "deliverables",
            "output",
            "result",
            "data",
        )
        for key in preferred_keys:
            if key in data:
                items.extend(self._collect_test_case_items(data[key]))
        if items:
            return items

        for value in data.values():
            items.extend(self._collect_test_case_items(value))
        return items

    def _is_test_case_dict(self, data: object) -> bool:
        """Heuristic to distinguish testcase dicts from wrapper metadata."""
        if not isinstance(data, dict):
            return False

        identity_keys = (
            "name",
            "title",
            "test_name",
            "case_name",
            "scenario",
            "objective",
            "description",
            "desc",
            "details",
            "summary",
        )
        evidence_keys = (
            "id",
            "test_id",
            "case_id",
            "tc_id",
            "steps",
            "test_steps",
            "procedure",
            "actions",
            "expected_result",
            "expectedResult",
            "expected_results",
            "expected",
            "validation_points",
            "priority",
            "preconditions",
            "postconditions",
            "test_type",
            "target",
            "test_data",
            "tags",
        )
        has_identity = any(
            isinstance(data.get(key), str) and data.get(key, "").strip()
            for key in identity_keys
        )
        has_evidence = any(key in data for key in evidence_keys)
        return has_identity and has_evidence

    def _items_to_test_cases(self, data: object) -> list[TestCase]:
        """Normalize extracted item dicts into TestCase models."""
        test_cases: list[TestCase] = []
        for i, item in enumerate(self._extract_test_case_items(data)):
            tc = self._dict_to_test_case(item, i)
            if tc:
                test_cases.append(tc)
        return test_cases

    def _cleanup_intermediates(self, work_dir: Path) -> None:
        """Remove transient test-design intermediate files after parsing."""
        intermediates_root = work_dir / "test_intermediates"
        if intermediates_root.exists():
            shutil.rmtree(intermediates_root)

    def _merge_test_cases(
        self,
        existing: list[TestCase],
        incoming: list[TestCase],
    ) -> list[TestCase]:
        """Merge testcase lists while preserving first-seen order by id."""
        merged: list[TestCase] = list(existing)
        seen = {tc.id for tc in existing}
        for tc in incoming:
            if tc.id in seen:
                continue
            merged.append(tc)
            seen.add(tc.id)
        return self._sort_test_cases(merged)

    def _sort_test_cases(self, test_cases: list[TestCase]) -> list[TestCase]:
        """Sort testcase ids like TC001 ahead of fallback alphanumeric ids."""
        def _key(tc: TestCase) -> tuple[int, int | str]:
            match = re.fullmatch(r"TC(\d+)", tc.id)
            if match:
                return (0, int(match.group(1)))
            return (1, tc.id)

        return sorted(test_cases, key=_key)

    def _parse_test_cases_from_text(self, raw_output: str) -> list[TestCase]:
        """Recover testcase objects from JSON-like text when strict parsing fails."""
        fragments = self._extract_test_case_fragments(raw_output)
        test_cases: list[TestCase] = []
        seen: set[str] = set()
        for fragment in fragments:
            tc = self._parse_test_case_fragment(fragment)
            if tc and tc.id not in seen:
                test_cases.append(tc)
                seen.add(tc.id)
        return test_cases

    def _extract_test_case_fragments(self, raw_output: str) -> list[str]:
        """Slice probable testcase object fragments using brace balancing."""
        fragments: list[str] = []
        for match in re.finditer(r'"id"\s*:\s*"TC[^"]+"', raw_output):
            start = raw_output.rfind("{", 0, match.start())
            if start == -1:
                continue

            depth = 0
            end = -1
            for index in range(start, len(raw_output)):
                char = raw_output[index]
                if char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        end = index + 1
                        break

            if end == -1:
                continue

            fragment = raw_output[start:end]
            if '"steps"' not in fragment and '"test_steps"' not in fragment:
                continue
            fragments.append(fragment)
        return fragments

    def _parse_test_case_fragment(self, fragment: str) -> TestCase | None:
        """Recover a testcase from a JSON-like object fragment."""
        tc_id = self._extract_line_value(fragment, "id")
        name = self._extract_line_value(fragment, "name")
        description = self._extract_line_value(fragment, "description")
        priority = self._extract_line_value(fragment, "priority") or "medium"
        expected_result = self._extract_line_value(fragment, "expected_result")

        steps: list[str] = []
        current_action = ""
        for raw_line in fragment.splitlines():
            line = raw_line.strip()
            action = self._extract_line_value(line, "action")
            expected = (
                self._extract_line_value(line, "expected")
                or self._extract_line_value(line, "expected_result")
            )

            if action and expected:
                steps.append(f"{action} -> 预期: {expected}")
                current_action = ""
                continue

            if action:
                current_action = action
                continue

            if current_action and expected:
                steps.append(f"{current_action} -> 预期: {expected}")
                current_action = ""

        if not expected_result and steps:
            expected_result = steps[-1].split("-> 预期:", 1)[-1].strip()

        if not tc_id or not (name or description):
            return None

        return TestCase(
            id=tc_id,
            name=name or description[:50],
            description=description or name,
            steps=steps,
            expected_result=expected_result,
            priority=priority,
        )

    def _extract_line_value(self, text: str, key: str) -> str:
        """Extract a JSON-like string value from a single line or fragment."""
        match = re.search(rf'"{re.escape(key)}"\s*:\s*"', text)
        if not match:
            return ""

        start = match.end()
        line_end = text.find("\n", start)
        if line_end == -1:
            line_end = len(text)
        candidate = text[start:line_end]
        if not candidate.strip():
            return ""
        for pattern in (
            r'^(.*?)(?=",\s*"[A-Za-z_][^"]*"\s*:)',
            r'^(.*)(?="\s*[},\]])',
        ):
            value_match = re.search(pattern, candidate)
            if value_match:
                return value_match.group(1).strip()
        return ""

    def _dict_to_test_case(self, data: dict, index: int) -> TestCase | None:
        """Convert a dict to a TestCase, handling various key formats."""
        try:
            tc_id = str(
                data.get(
                    "id",
                    data.get(
                        "test_id",
                        data.get("case_id", data.get("tc_id", f"tc_{index + 1}")),
                    ),
                )
            )
            name = data.get(
                "name",
                data.get(
                    "title",
                    data.get(
                        "test_name",
                        data.get(
                            "case_name",
                            data.get("scenario", data.get("objective", "")),
                        ),
                    ),
                ),
            )
            description = data.get(
                "description",
                data.get(
                    "desc",
                    data.get(
                        "details",
                        data.get("summary", data.get("objective", "")),
                    ),
                ),
            )
            raw_steps = data.get(
                "steps",
                data.get(
                    "test_steps",
                    data.get("procedure", data.get("actions", data.get("validation_points", []))),
                ),
            )

            # Normalize steps to list[str]
            steps: list[str] = []
            if isinstance(raw_steps, str):
                steps = [raw_steps]
            elif isinstance(raw_steps, list):
                for s in raw_steps:
                    if isinstance(s, str):
                        steps.append(s)
                    elif isinstance(s, dict):
                        # structured step format: {"step": 1, "action": "...", "expected_result": "..."}
                        action = s.get(
                            "action",
                            s.get(
                                "description",
                                s.get("step_name", s.get("step", "")),
                            ),
                        )
                        expected = s.get(
                            "expected_result",
                            s.get(
                                "expected",
                                s.get("expected_outcome", s.get("outcome", "")),
                            ),
                        )
                        if action and expected:
                            steps.append(f"{action} -> 预期: {expected}")
                        elif action:
                            steps.append(action)

            # Extract expected_result: try top-level first, then last step's expected
            expected = data.get(
                "expected_result",
                data.get(
                    "expectedResult",
                    data.get(
                        "expected",
                        data.get("expected_outcome", data.get("expected_results", "")),
                    ),
                ),
            )
            if isinstance(expected, list):
                expected = "；".join(str(item) for item in expected if str(item).strip())
            if not expected and isinstance(raw_steps, list) and raw_steps:
                last_step = raw_steps[-1]
                if isinstance(last_step, dict):
                    expected = last_step.get(
                        "expected_result",
                        last_step.get(
                            "expected",
                            last_step.get("expected_outcome", last_step.get("outcome", "")),
                        ),
                    )

            priority = data.get("priority", "medium")

            if not name and not description:
                return None

            return TestCase(
                id=tc_id,
                name=name or description[:50],
                description=description or name,
                steps=steps,
                expected_result=expected,
                priority=priority,
            )
        except Exception:
            return None


def _find_json_blocks(text: str) -> list[str]:
    """Find JSON array or object blocks in text."""
    blocks: list[str] = []
    decoder = json.JSONDecoder()
    seen_ranges: set[tuple[int, int]] = set()
    for i, ch in enumerate(text):
        if ch not in ("{", "["):
            continue
        try:
            _, end = decoder.raw_decode(text[i:])
        except json.JSONDecodeError:
            continue
        json_range = (i, i + end)
        if json_range in seen_ranges:
            continue
        seen_ranges.add(json_range)
        blocks.append(text[i : i + end])
    return blocks


def _find_structural_json_blocks(text: str) -> list[str]:
    """Find balanced JSON-like blocks without requiring valid string escaping."""
    blocks: list[str] = []
    stack: list[str] = []
    start: int | None = None
    for index, char in enumerate(text):
        if char in "{[":
            if start is None:
                start = index
            stack.append("}" if char == "{" else "]")
            continue
        if char in "}]":
            if not stack:
                start = None
                continue
            expected = stack.pop()
            if char != expected:
                stack.clear()
                start = None
                continue
            if not stack and start is not None:
                blocks.append(text[start : index + 1])
                start = None
    return blocks


def _repair_jsonish_text(text: str) -> str:
    """Escape common unescaped quotes inside JSON string values."""
    chars: list[str] = []
    in_string = False
    escaping = False
    length = len(text)

    def _next_significant(pos: int) -> str:
        while pos < length and text[pos].isspace():
            pos += 1
        return text[pos] if pos < length else ""

    for index, char in enumerate(text):
        if not in_string:
            chars.append(char)
            if char == '"':
                in_string = True
                escaping = False
            continue

        if escaping:
            chars.append(char)
            escaping = False
            continue

        if char == "\\":
            chars.append(char)
            escaping = True
            continue

        if char == '"':
            next_char = _next_significant(index + 1)
            if next_char in (",", "}", "]", ":"):
                chars.append(char)
                in_string = False
            else:
                chars.append('\\"')
            continue

        chars.append(char)

    return "".join(chars)
