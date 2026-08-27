"""运行时错误提取。

从 E2E 测试结果中提取运行时错误（页面未找到、JS 异常、JS 错误、白屏），
生成符合跨仓库契约的 error 条目。

零误报红线：
* console_errors 仅当 ``json.loads`` 成功且 ``source`` 与配置的
  runtime_error_source 匹配时才提取；解析失败或 source 不匹配一律忽略；
* runtime_error_source 为空时跳过 console_errors 采集（返回空）；
* 白屏仅当 ``verifications.white_screen.detected is True`` 时才提取
  （与 ``test_phase._result_has_white_screen`` 判定口径一致）。

上游信号说明：
* 壳工程在 Web 端通过 ``console.error`` 输出单参数 JSON 字符串，
  source 由 runtime_error_source 配置指定，type 为 ``page_not_found`` 或 ``js_exception``；
* ai-ui-test 的 Playwright 采集后落在
  ``verifications.page_diagnostics.console_errors[].message``（即 text()）和 ``args[0]``；
* 未捕获 JS 异常在 ``verifications.page_diagnostics.js_errors[]``，
  含 type/name/message/stack，其中 type 为 ``pageerror`` 或 ``unhandledrejection``。
"""

from __future__ import annotations

import json

from ...utils.logging import get_logger

logger = get_logger(__name__)


def _get_runtime_error_source() -> str:
    """从配置读取 runtime_error_source，空字符串表示不采集。"""
    try:
        from ...config import get_config
        return get_config().runtime_error_source
    except Exception:
        return ""


#: 每平台 errors 上限（超出由 write_runtime_errors 截断）
MAX_ERRORS_PER_PLATFORM = 50


def extract_runtime_errors(test_results: list) -> list[dict]:
    """从测试结果列表中提取运行时错误条目。

    遍历各用例的 ``verifications.page_diagnostics``（console_errors / js_errors）
    以及 ``verifications.white_screen``，生成标准化的错误条目。

    零误报原则：
    - console_errors 仅当 json.loads 成功且 source 匹配配置值时才提取；
    - runtime_error_source 为空时跳过 console_errors 采集；
    - 解析失败或 source 不匹配一律忽略；
    - 白屏仅当 detected is True 时才提取。

    去重：同用例同 type+page+message 去重（用 set 跟踪）。

    Args:
        test_results: TestCaseResult 对象列表（或具有 test_case_id /
            verifications 属性的对象）。

    Returns:
        错误条目列表，每个条目符合跨仓库契约 schema。无错误时返回空列表。
    """
    runtime_error_source = _get_runtime_error_source()
    errors: list[dict] = []
    seen: set[tuple] = set()

    for tr in test_results or []:
        tc_id = getattr(tr, "test_case_id", "") or getattr(tr, "id", "")
        verifications = getattr(tr, "verifications", None)
        if not isinstance(verifications, dict) or not verifications:
            continue

        page_diag = verifications.get("page_diagnostics")
        console_errors: list = []
        js_errors: list = []
        generator_console_items: list[dict] = []

        if isinstance(page_diag, dict):
            raw_ce = page_diag.get("console_errors")
            if isinstance(raw_ce, list):
                console_errors = raw_ce
            raw_je = page_diag.get("js_errors")
            if isinstance(raw_je, list):
                js_errors = raw_je

        # 1. 解析 console_errors -> page_not_found / js_exception
        #    仅当 runtime_error_source 非空时才采集（零误报）
        for ce in console_errors:
            if not runtime_error_source:
                break  # 配置为空时完全跳过 console_errors 采集
            if not isinstance(ce, dict):
                continue
            text = _extract_console_text(ce)
            if not text:
                continue
            payload = _try_parse_json(text)
            if payload is None:
                continue  # 零误报：非 JSON 一律忽略
            if not isinstance(payload, dict):
                continue
            if payload.get("source") != runtime_error_source:
                continue  # 零误报：source 不匹配一律忽略

            entry = _build_console_entry(payload, tc_id)
            if entry is None:
                continue

            dedup_key = (
                tc_id,
                entry["type"],
                entry.get("page", ""),
                entry.get("message", ""),
            )
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            errors.append(entry)
            generator_console_items.append(ce)

        # 2. 解析 js_errors -> js_error
        for je in js_errors:
            if not isinstance(je, dict):
                continue
            entry = {
                "type": "js_error",
                "message": je.get("message", ""),
                "stack": je.get("stack", ""),
                "name": je.get("name", ""),
                "source": "pageerror",
                "test_case_id": tc_id,
            }
            dedup_key = (tc_id, "js_error", "", entry["message"])
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            errors.append(entry)

        # 3. 白屏检测 -> white_screen
        ws = verifications.get("white_screen")
        if isinstance(ws, dict) and ws.get("detected") is True:
            entry = {
                "type": "white_screen",
                "message": f"{tc_id} 白屏",
                "evidence": {
                    "js_errors": list(js_errors),
                    "console_errors": list(generator_console_items),
                },
                "source": "white_screen_gate",
                "test_case_id": tc_id,
            }
            dedup_key = (tc_id, "white_screen", "", entry["message"])
            if dedup_key not in seen:
                seen.add(dedup_key)
                errors.append(entry)

    return errors


def _extract_console_text(ce: dict) -> str | None:
    """从 console_error 条目中提取文本：优先 args[0]，回退 message。"""
    args = ce.get("args")
    if isinstance(args, list) and args:
        first = args[0]
        if isinstance(first, str):
            return first
    msg = ce.get("message", "")
    if isinstance(msg, str):
        return msg
    return None


def _try_parse_json(text: str) -> object | None:
    """安全解析 JSON 字符串，失败时返回 None（零误报）。"""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def _build_console_entry(payload: dict, tc_id: str) -> dict | None:
    """根据 JSON payload 构建错误条目。

    仅处理 type 为 page_not_found / js_exception 的 payload；
    未知 type 返回 None（零误报）。
    """
    err_type = payload.get("type", "")
    if err_type == "page_not_found":
        return {
            "type": "page_not_found",
            "message": payload.get("message", ""),
            "page": payload.get("page", ""),
            "timestamp": payload.get("timestamp", 0),
            "source": "shell_console",
            "test_case_id": tc_id,
        }
    if err_type == "js_exception":
        return {
            "type": "js_exception",
            "message": payload.get("message", ""),
            "stack": payload.get("stack", ""),
            "timestamp": payload.get("timestamp", 0),
            "source": "error_boundary",
            "test_case_id": tc_id,
        }
    return None


def compute_runtime_errors_summary(errors: list[dict], truncated: bool) -> dict:
    """根据错误条目列表计算 summary 统计。

    Args:
        errors: 已截断后的错误条目列表。
        truncated: 是否发生了截断。

    Returns:
        summary dict，包含各类型计数、总数与 truncated 标志。
    """
    counts = {
        "page_not_found_count": 0,
        "js_exception_count": 0,
        "js_error_count": 0,
        "white_screen_count": 0,
    }
    for err in errors:
        t = err.get("type", "")
        if t == "page_not_found":
            counts["page_not_found_count"] += 1
        elif t == "js_exception":
            counts["js_exception_count"] += 1
        elif t == "js_error":
            counts["js_error_count"] += 1
        elif t == "white_screen":
            counts["white_screen_count"] += 1
    return {
        **counts,
        "total_error_count": sum(counts.values()),
        "truncated": truncated,
    }
