"""测试 Expo 运行时错误提取与落盘。

覆盖：
- extract_runtime_errors 的 source 过滤与解析失败忽略（零误报）
- page_not_found / js_exception / js_error / white_screen 各类型条目生成
- 去重逻辑（同用例同 type+page+message）
- 50 条截断 + truncated 标志（write_runtime_errors）
- write_runtime_errors 多平台并发写入合并
- 空 errors 不创建文件
"""

from __future__ import annotations

import json

import pytest

from evalapp.config import Config, reset_config_cache, set_config
from evalapp.evaluation.results.models import TestCaseResult
from evalapp.evaluation.runner.runtime_errors import extract_runtime_errors
from evalapp.workspace.sample_data import write_runtime_errors

# 通用运行时错误来源标识（生成器无关）；由 config.runtime_error_source 驱动。
_RUNTIME_SOURCE = "app-crossplatform-h5"


@pytest.fixture(autouse=True)
def _set_runtime_error_source():
    """默认让 config.runtime_error_source 指向测试用 source，使 console_errors 采集生效。

    去掉生成器特判后 source 由 config.runtime_error_source 驱动，默认空表示不采集；
    多数提取用例需要一个非空 source 才能验证解析逻辑，故在此统一注入并在结束后还原。
    """
    set_config(Config(runtime_error_source=_RUNTIME_SOURCE))
    yield
    reset_config_cache()


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------


def _make_payload(
    *,
    type: str,
    message: str = "",
    page: str = "",
    stack: str = "",
    timestamp: int = 0,
) -> str:
    """构建配置来源（runtime_error_source）的 console.error JSON 字符串。"""
    payload: dict = {"source": _RUNTIME_SOURCE, "type": type, "message": message}
    if page:
        payload["page"] = page
    if stack:
        payload["stack"] = stack
    if timestamp:
        payload["timestamp"] = timestamp
    return json.dumps(payload, ensure_ascii=False)


def _make_console_error(message: str = "", args: list | None = None) -> dict:
    """构建 console_error 条目。"""
    entry: dict = {"level": "error", "message": message}
    if args is not None:
        entry["args"] = args
    return entry


def _make_js_error(
    *,
    name: str = "TypeError",
    message: str = "error",
    stack: str = "at line 1",
    type: str = "pageerror",
) -> dict:
    """构建 js_error 条目。"""
    return {"type": type, "name": name, "message": message, "stack": stack}


def _tc_result(
    *,
    tc_id: str = "TC_LAUNCH",
    passed: bool = False,
    console_errors: list[dict] | None = None,
    js_errors: list[dict] | None = None,
    white_screen: bool = False,
) -> TestCaseResult:
    """构建带 page_diagnostics 的 TestCaseResult。"""
    verifications: dict = {}
    page_diag: dict = {}
    if console_errors is not None:
        page_diag["console_errors"] = console_errors
    if js_errors is not None:
        page_diag["js_errors"] = js_errors
    if page_diag:
        verifications["page_diagnostics"] = page_diag
    if white_screen:
        verifications["white_screen"] = {"detected": True}
    return TestCaseResult(
        test_case_id=tc_id,
        passed=passed,
        status="FAIL" if not passed else "PASS",
        verifications=verifications if verifications else None,
    )


def _make_error(*, type: str = "js_error", message: str = "err", **kwargs) -> dict:
    """构建一个最小错误条目（用于 write_runtime_errors 测试）。"""
    entry: dict = {"type": type, "message": message, "test_case_id": "TC1"}
    entry.update(kwargs)
    return entry


# ---------------------------------------------------------------------------
# extract_runtime_errors — source 过滤与解析失败忽略
# ---------------------------------------------------------------------------


class TestExtractSourceFiltering:
    """source 过滤与解析失败忽略（零误报红线）。"""

    def test_non_json_message_ignored(self):
        """非 JSON 的 console.error message 一律忽略。"""
        ce = _make_console_error(message="this is not json")
        tr = _tc_result(console_errors=[ce])
        assert extract_runtime_errors([tr]) == []

    def test_wrong_source_ignored(self):
        """JSON 但 source 不匹配一律忽略。"""
        payload = json.dumps(
            {"source": "other-source", "type": "page_not_found", "message": "test"}
        )
        ce = _make_console_error(message=payload)
        tr = _tc_result(console_errors=[ce])
        assert extract_runtime_errors([tr]) == []

    def test_unknown_type_ignored(self):
        """source 匹配但 type 未知的 payload 一律忽略。"""
        payload = json.dumps(
            {"source": _RUNTIME_SOURCE, "type": "unknown_type", "message": "test"}
        )
        ce = _make_console_error(args=[payload])
        tr = _tc_result(console_errors=[ce])
        assert extract_runtime_errors([tr]) == []

    def test_correct_source_extracted(self):
        """JSON 且 source 匹配时提取。"""
        payload = _make_payload(type="page_not_found", message="not found", page="/x")
        ce = _make_console_error(message=payload)
        tr = _tc_result(console_errors=[ce])
        errors = extract_runtime_errors([tr])
        assert len(errors) == 1
        assert errors[0]["type"] == "page_not_found"

    def test_args_zero_priority_over_message(self):
        """args[0] 优先于 message。"""
        payload = _make_payload(type="page_not_found", message="from_args", page="/a")
        ce = _make_console_error(message="raw text", args=[payload])
        tr = _tc_result(console_errors=[ce])
        errors = extract_runtime_errors([tr])
        assert len(errors) == 1
        assert errors[0]["message"] == "from_args"

    def test_args_non_string_fallback_to_message(self):
        """args[0] 非字符串时回退到 message。"""
        payload = _make_payload(type="page_not_found", message="from_msg", page="/b")
        ce = _make_console_error(message=payload, args=[123])
        tr = _tc_result(console_errors=[ce])
        errors = extract_runtime_errors([tr])
        assert len(errors) == 1
        assert errors[0]["message"] == "from_msg"

    def test_no_verifications_skipped(self):
        """verifications 为 None 的用例跳过。"""
        tr = TestCaseResult(test_case_id="TC1", passed=True, status="PASS")
        assert extract_runtime_errors([tr]) == []

    def test_empty_test_results(self):
        """空列表 / None 返回空。"""
        assert extract_runtime_errors([]) == []
        assert extract_runtime_errors(None) == []

    def test_non_dict_console_error_skipped(self):
        """非 dict 的 console_error 条目跳过。"""
        payload = _make_payload(type="page_not_found", message="m", page="/p")
        ce = _make_console_error(args=[payload])
        tr = _tc_result(console_errors=[ce, "not a dict", 42])
        errors = extract_runtime_errors([tr])
        assert len(errors) == 1

    def test_empty_source_skips_console_collection(self):
        """runtime_error_source 为空时不采集 console_errors（零误报）。"""
        set_config(Config(runtime_error_source=""))
        payload = _make_payload(type="page_not_found", message="m", page="/p")
        ce = _make_console_error(args=[payload])
        tr = _tc_result(console_errors=[ce])
        assert extract_runtime_errors([tr]) == []

    def test_configured_source_collected(self):
        """runtime_error_source 设为某 source 值时正常采集匹配项。"""
        set_config(Config(runtime_error_source="custom-source"))
        payload = json.dumps(
            {
                "source": "custom-source",
                "type": "page_not_found",
                "message": "hit",
                "page": "/c",
            }
        )
        ce = _make_console_error(args=[payload])
        tr = _tc_result(console_errors=[ce])
        errors = extract_runtime_errors([tr])
        assert len(errors) == 1
        assert errors[0]["type"] == "page_not_found"
        assert errors[0]["message"] == "hit"


# ---------------------------------------------------------------------------
# extract_runtime_errors — 各类型条目生成
# ---------------------------------------------------------------------------


class TestExtractPageNotFound:
    """page_not_found 条目生成。"""

    def test_entry_fields(self):
        payload = _make_payload(
            type="page_not_found",
            message="Page not found",
            page="/settings",
            timestamp=1722849600000,
        )
        ce = _make_console_error(args=[payload])
        tr = _tc_result(console_errors=[ce])
        errors = extract_runtime_errors([tr])
        assert len(errors) == 1
        entry = errors[0]
        assert entry["type"] == "page_not_found"
        assert entry["message"] == "Page not found"
        assert entry["page"] == "/settings"
        assert entry["timestamp"] == 1722849600000
        assert entry["source"] == "shell_console"
        assert entry["test_case_id"] == "TC_LAUNCH"


class TestExtractJsException:
    """js_exception 条目生成。"""

    def test_entry_fields(self):
        payload = _make_payload(
            type="js_exception",
            message="Uncaught Error",
            stack="Error: at line 5",
            timestamp=100,
        )
        ce = _make_console_error(args=[payload])
        tr = _tc_result(console_errors=[ce])
        errors = extract_runtime_errors([tr])
        assert len(errors) == 1
        entry = errors[0]
        assert entry["type"] == "js_exception"
        assert entry["message"] == "Uncaught Error"
        assert entry["stack"] == "Error: at line 5"
        assert entry["timestamp"] == 100
        assert entry["source"] == "error_boundary"
        assert entry["test_case_id"] == "TC_LAUNCH"


class TestExtractJsError:
    """js_error 条目生成。"""

    def test_entry_fields(self):
        je = _make_js_error(
            name="TypeError", message="Cannot read property", stack="at line 1"
        )
        tr = _tc_result(js_errors=[je])
        errors = extract_runtime_errors([tr])
        assert len(errors) == 1
        entry = errors[0]
        assert entry["type"] == "js_error"
        assert entry["message"] == "Cannot read property"
        assert entry["stack"] == "at line 1"
        assert entry["name"] == "TypeError"
        assert entry["source"] == "pageerror"
        assert entry["test_case_id"] == "TC_LAUNCH"

    def test_unhandledrejection_also_js_error(self):
        """type=unhandledrejection 的 js_error 同样提取，source 统一为 pageerror。"""
        je = _make_js_error(
            type="unhandledrejection", message="promise rejection", stack="at line 3"
        )
        tr = _tc_result(js_errors=[je])
        errors = extract_runtime_errors([tr])
        assert len(errors) == 1
        assert errors[0]["source"] == "pageerror"


class TestExtractWhiteScreen:
    """white_screen 条目生成。"""

    def test_entry_fields_with_evidence(self):
        je = _make_js_error(
            name="ReferenceError", message="x is not defined", stack="at line 2"
        )
        payload = _make_payload(type="page_not_found", message="not found", page="/missing")
        ce = _make_console_error(args=[payload])
        tr = _tc_result(console_errors=[ce], js_errors=[je], white_screen=True)
        errors = extract_runtime_errors([tr])
        # 应有 3 条：page_not_found + js_error + white_screen
        types = [e["type"] for e in errors]
        assert "page_not_found" in types
        assert "js_error" in types
        assert "white_screen" in types

        ws_entry = next(e for e in errors if e["type"] == "white_screen")
        assert ws_entry["source"] == "white_screen_gate"
        assert ws_entry["test_case_id"] == "TC_LAUNCH"
        assert "白屏" in ws_entry["message"]
        # evidence 内嵌同期的 js_errors 和配置来源 console_errors
        assert len(ws_entry["evidence"]["js_errors"]) == 1
        assert ws_entry["evidence"]["js_errors"][0]["name"] == "ReferenceError"
        assert len(ws_entry["evidence"]["console_errors"]) == 1

    def test_white_screen_not_detected_no_entry(self):
        """white_screen.detected 非 True 时不生成条目。"""
        tr = TestCaseResult(
            test_case_id="TC1",
            passed=True,
            status="PASS",
            verifications={"white_screen": {"detected": False}},
        )
        assert extract_runtime_errors([tr]) == []

    def test_white_screen_missing_field_no_entry(self):
        """white_screen 字段缺失时不生成条目。"""
        tr = TestCaseResult(
            test_case_id="TC1",
            passed=True,
            status="PASS",
            verifications={"other": {}},
        )
        assert extract_runtime_errors([tr]) == []

    def test_evidence_only_matching_source_console(self):
        """evidence.console_errors 仅含配置来源匹配的条目。"""
        matched_payload = _make_payload(
            type="page_not_found", message="matched", page="/f"
        )
        normal_ce = _make_console_error(message="normal error text")
        ce = _make_console_error(args=[matched_payload])
        je = _make_js_error(message="js")
        tr = _tc_result(console_errors=[ce, normal_ce], js_errors=[je], white_screen=True)
        errors = extract_runtime_errors([tr])
        ws = next(e for e in errors if e["type"] == "white_screen")
        # evidence.console_errors 仅含配置来源匹配的 1 条
        assert len(ws["evidence"]["console_errors"]) == 1
        # evidence.js_errors 含全部 js_errors
        assert len(ws["evidence"]["js_errors"]) == 1


# ---------------------------------------------------------------------------
# extract_runtime_errors — 去重逻辑
# ---------------------------------------------------------------------------


class TestExtractDedup:
    """去重逻辑：同用例同 type+page+message 去重。"""

    def test_duplicate_page_not_found_deduped(self):
        payload = _make_payload(type="page_not_found", message="same", page="/same")
        ce1 = _make_console_error(args=[payload])
        ce2 = _make_console_error(args=[payload])
        tr = _tc_result(console_errors=[ce1, ce2])
        errors = extract_runtime_errors([tr])
        assert len(errors) == 1

    def test_different_page_not_deduped(self):
        payload1 = _make_payload(type="page_not_found", message="msg", page="/a")
        payload2 = _make_payload(type="page_not_found", message="msg", page="/b")
        ce1 = _make_console_error(args=[payload1])
        ce2 = _make_console_error(args=[payload2])
        tr = _tc_result(console_errors=[ce1, ce2])
        errors = extract_runtime_errors([tr])
        assert len(errors) == 2

    def test_duplicate_js_error_deduped(self):
        je1 = _make_js_error(message="same error")
        je2 = _make_js_error(message="same error")
        tr = _tc_result(js_errors=[je1, je2])
        errors = extract_runtime_errors([tr])
        js_errs = [e for e in errors if e["type"] == "js_error"]
        assert len(js_errs) == 1

    def test_different_message_not_deduped(self):
        je1 = _make_js_error(message="error A")
        je2 = _make_js_error(message="error B")
        tr = _tc_result(js_errors=[je1, je2])
        errors = extract_runtime_errors([tr])
        js_errs = [e for e in errors if e["type"] == "js_error"]
        assert len(js_errs) == 2

    def test_different_test_case_not_deduped(self):
        payload = _make_payload(type="page_not_found", message="same", page="/same")
        ce = _make_console_error(args=[payload])
        tr1 = _tc_result(tc_id="TC1", console_errors=[ce])
        tr2 = _tc_result(tc_id="TC2", console_errors=[ce])
        errors = extract_runtime_errors([tr1, tr2])
        assert len(errors) == 2
        assert errors[0]["test_case_id"] == "TC1"
        assert errors[1]["test_case_id"] == "TC2"


class TestExtractMixedTypes:
    """多种错误类型混合提取。"""

    def test_all_types_in_one_case(self):
        pnf_payload = _make_payload(type="page_not_found", message="pnf", page="/p")
        js_exc_payload = _make_payload(
            type="js_exception", message="exc", stack="s"
        )
        ce1 = _make_console_error(args=[pnf_payload])
        ce2 = _make_console_error(args=[js_exc_payload])
        je = _make_js_error(message="js err")
        tr = _tc_result(
            console_errors=[ce1, ce2], js_errors=[je], white_screen=True
        )
        errors = extract_runtime_errors([tr])
        types = {e["type"] for e in errors}
        assert types == {"page_not_found", "js_exception", "js_error", "white_screen"}


# ---------------------------------------------------------------------------
# write_runtime_errors — 落盘与并发合并
# ---------------------------------------------------------------------------


@pytest.fixture
def workspace(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


class TestWriteRuntimeErrors:
    """write_runtime_errors 落盘与并发合并。"""

    def test_empty_errors_no_file(self, workspace):
        """空 errors 不创建文件。"""
        write_runtime_errors(workspace, "SampleA", "expo_web", [])
        assert not (workspace / "SampleA" / "runtime_errors.json").exists()

    def test_write_creates_file_with_schema(self, workspace):
        errors = [_make_error(type="page_not_found", message="m", page="/x")]
        write_runtime_errors(workspace, "SampleA", "expo_web", errors)
        path = workspace / "SampleA" / "runtime_errors.json"
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["schema_version"] == "1.0"
        assert "expo_web" in data["platforms"]
        assert data["platforms"]["expo_web"]["errors"][0]["type"] == "page_not_found"

    def test_summary_computation(self, workspace):
        errors = [
            _make_error(type="page_not_found", message="a", page="/1"),
            _make_error(type="page_not_found", message="b", page="/2"),
            _make_error(type="js_exception", message="c"),
            _make_error(type="js_error", message="d"),
            _make_error(type="white_screen", message="ws"),
        ]
        write_runtime_errors(workspace, "SampleA", "expo_web", errors)
        data = json.loads(
            (workspace / "SampleA" / "runtime_errors.json").read_text()
        )
        summary = data["platforms"]["expo_web"]["summary"]
        assert summary["page_not_found_count"] == 2
        assert summary["js_exception_count"] == 1
        assert summary["js_error_count"] == 1
        assert summary["white_screen_count"] == 1
        assert summary["total_error_count"] == 5
        assert summary["truncated"] is False

    def test_truncation_at_50(self, workspace):
        """超过 50 条截断并置 truncated=true。"""
        errors = [
            _make_error(type="js_error", message=f"err-{i}") for i in range(60)
        ]
        write_runtime_errors(workspace, "SampleA", "expo_web", errors)
        data = json.loads(
            (workspace / "SampleA" / "runtime_errors.json").read_text()
        )
        platform = data["platforms"]["expo_web"]
        assert len(platform["errors"]) == 50
        assert platform["summary"]["truncated"] is True
        assert platform["summary"]["total_error_count"] == 50
        # 截断保留前 50 条
        assert platform["errors"][0]["message"] == "err-0"
        assert platform["errors"][49]["message"] == "err-49"

    def test_no_truncation_at_exactly_50(self, workspace):
        """恰好 50 条不截断，truncated=false。"""
        errors = [
            _make_error(type="js_error", message=f"err-{i}") for i in range(50)
        ]
        write_runtime_errors(workspace, "SampleA", "expo_web", errors)
        data = json.loads(
            (workspace / "SampleA" / "runtime_errors.json").read_text()
        )
        platform = data["platforms"]["expo_web"]
        assert len(platform["errors"]) == 50
        assert platform["summary"]["truncated"] is False

    def test_multi_platform_merge(self, workspace):
        """两次调用不同 platform，最终 platforms 含两个键。"""
        errors_web = [_make_error(type="page_not_found", message="web", page="/w")]
        errors_ios = [_make_error(type="js_exception", message="ios")]
        write_runtime_errors(workspace, "SampleA", "expo_web", errors_web)
        write_runtime_errors(workspace, "SampleA", "expo_ios", errors_ios)
        data = json.loads(
            (workspace / "SampleA" / "runtime_errors.json").read_text()
        )
        assert set(data["platforms"].keys()) == {"expo_web", "expo_ios"}
        assert data["platforms"]["expo_web"]["errors"][0]["page"] == "/w"
        assert data["platforms"]["expo_ios"]["errors"][0]["message"] == "ios"
        # schema_version 保持
        assert data["schema_version"] == "1.0"

    def test_same_platform_overwrite(self, workspace):
        """同平台再次写入覆盖旧数据。"""
        errors1 = [_make_error(type="page_not_found", message="old", page="/o")]
        write_runtime_errors(workspace, "SampleA", "expo_web", errors1)
        errors2 = [_make_error(type="js_error", message="new")]
        write_runtime_errors(workspace, "SampleA", "expo_web", errors2)
        data = json.loads(
            (workspace / "SampleA" / "runtime_errors.json").read_text()
        )
        platform = data["platforms"]["expo_web"]
        assert len(platform["errors"]) == 1
        assert platform["errors"][0]["message"] == "new"
        assert platform["summary"]["page_not_found_count"] == 0
        assert platform["summary"]["js_error_count"] == 1

    def test_empty_errors_does_not_modify_existing(self, workspace):
        """空 errors 不改现有文件。"""
        errors = [_make_error(type="page_not_found", message="exists", page="/e")]
        write_runtime_errors(workspace, "SampleA", "expo_web", errors)
        path = workspace / "SampleA" / "runtime_errors.json"
        original = json.loads(path.read_text())
        # 再次以空 errors 调用
        write_runtime_errors(workspace, "SampleA", "expo_web", [])
        # 文件内容不变
        assert json.loads(path.read_text()) == original

    def test_corrupted_json_reset(self, workspace):
        """runtime_errors.json 损坏时重置而非崩溃。"""
        sample_dir = workspace / "SampleA"
        sample_dir.mkdir(parents=True, exist_ok=True)
        # 写入损坏的 JSON
        (sample_dir / "runtime_errors.json").write_text("NOT JSON{")
        errors = [_make_error(type="js_error", message="recovered")]
        write_runtime_errors(workspace, "SampleA", "expo_web", errors)
        data = json.loads(
            (workspace / "SampleA" / "runtime_errors.json").read_text()
        )
        assert data["platforms"]["expo_web"]["errors"][0]["message"] == "recovered"


# ---------------------------------------------------------------------------
# 集成测试：extract + write 端到端
# ---------------------------------------------------------------------------


class TestExtractAndWriteIntegration:
    """extract_runtime_errors → write_runtime_errors 端到端验证。"""

    def test_extract_then_write(self, workspace):
        """从 TestCaseResult 提取后写入 runtime_errors.json。"""
        payload = _make_payload(
            type="page_not_found", message="Page missing", page="/gone"
        )
        ce = _make_console_error(args=[payload])
        je = _make_js_error(name="RangeError", message="out of range")
        tr = _tc_result(
            tc_id="TC_LAUNCH", console_errors=[ce], js_errors=[je]
        )

        errors = extract_runtime_errors([tr])
        assert len(errors) == 2

        write_runtime_errors(workspace, "MyApp", "expo_web", errors)
        data = json.loads(
            (workspace / "MyApp" / "runtime_errors.json").read_text()
        )
        platform = data["platforms"]["expo_web"]
        assert len(platform["errors"]) == 2
        assert platform["summary"]["page_not_found_count"] == 1
        assert platform["summary"]["js_error_count"] == 1
        assert platform["summary"]["total_error_count"] == 2

    def test_no_errors_no_file(self, workspace):
        """提取结果为空时不创建文件。"""
        tr = _tc_result(tc_id="TC_LAUNCH", console_errors=[], js_errors=[])
        errors = extract_runtime_errors([tr])
        assert errors == []
        write_runtime_errors(workspace, "MyApp", "expo_web", errors)
        assert not (workspace / "MyApp" / "runtime_errors.json").exists()
