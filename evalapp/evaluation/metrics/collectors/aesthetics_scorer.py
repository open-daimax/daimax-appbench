"""美观度评分 - VL 模型调用与结果解析。

负责构造多模态请求、调用 OpenAI 兼容 API、解析模型返回的 JSON 评分结果。
"""
from __future__ import annotations

import base64
import json
import logging
import mimetypes
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from .aesthetics_prompt import RULE_VERSION, USER_INSTRUCTION, build_system_prompt

logger = logging.getLogger(__name__)

# 超时与重试配置
REQUEST_TIMEOUT = 300  # 秒，dashscope VL 模型高峰延迟高
MAX_RETRIES = 3
BACKOFF_BASE = 5  # 退避：5s, 15s, 45s (5 * 3^attempt)


@dataclass
class ScoringResult:
    """美观度评分结果。"""
    overall: float = 0.0
    dimensions: dict[str, float] = field(default_factory=dict)
    comment: str = ""
    issues: list[str] = field(default_factory=list)
    scored_frames: list[str] = field(default_factory=list)
    rule_version: str = RULE_VERSION
    penalized_frames: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    cost_usd: float = 0.0


@dataclass
class ModelConfig:
    """模型配置。"""
    base_url: str = ""
    api_key: str = ""
    name: str = ""


def score_frames(
    frames: list[Path],
    app_category: str,
    model_config: ModelConfig,
) -> ScoringResult:
    """调用 VL 模型对截图帧进行美观度评分。

    Args:
        frames: 参与评分的截图路径列表
        app_category: 应用品类
        model_config: 模型配置（base_url, api_key, name）

    Returns:
        ScoringResult 评分结果

    Raises:
        RuntimeError: 所有重试均失败
    """
    # 构造 messages
    system_prompt = build_system_prompt(app_category)

    # 构造 user 消息内容：文本指令 + N 张图片
    content_parts: list[dict] = []
    scored_frame_names: list[str] = []

    for frame_path in frames:
        data_uri = _image_to_data_uri(frame_path)
        if data_uri:
            content_parts.append({
                "type": "image_url",
                "image_url": {"url": data_uri},
            })
            scored_frame_names.append(str(frame_path.relative_to(frame_path.parent.parent)))

    # 文本指令放最后
    content_parts.append({"type": "text", "text": USER_INSTRUCTION})

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": content_parts},
    ]

    # 重试调用
    last_error: Exception | None = None
    raw_response = ""
    usage_info: dict = {}

    for attempt in range(MAX_RETRIES):
        if attempt > 0:
            backoff = BACKOFF_BASE * (3 ** attempt)
            logger.info("美观度评分重试 %d/%d，等待 %ds", attempt + 1, MAX_RETRIES, backoff)
            time.sleep(backoff)

        try:
            raw_response, usage_info = _call_api(messages, model_config)
            break
        except Exception as e:
            last_error = e
            logger.warning("美观度评分 API 调用失败 (attempt %d): %s", attempt + 1, e)
    else:
        raise RuntimeError(f"美观度评分 API 调用 {MAX_RETRIES} 次均失败: {last_error}")

    # 解析结果
    parsed = parse_scoring_result(raw_response)

    # 过滤幻觉扣分图
    penalized = parsed.get("penalized_frames", [])
    penalized = filter_penalized_frames(penalized, scored_frame_names)

    return ScoringResult(
        overall=float(parsed.get("overall", 0)),
        dimensions=parsed.get("dimensions", {}),
        comment=parsed.get("comment", ""),
        issues=parsed.get("issues", []),
        scored_frames=scored_frame_names,
        rule_version=RULE_VERSION,
        penalized_frames=penalized,
        usage=usage_info,
    )


def _call_api(messages: list[dict], config: ModelConfig) -> tuple[str, dict]:
    """调用 OpenAI 兼容的 chat/completions API。

    Returns:
        (模型返回的文本内容, usage 字典)
    """
    url = f"{config.base_url.rstrip('/')}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config.api_key}",
    }
    payload = {
        "model": config.name,
        "messages": messages,
    }

    with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
        resp = client.post(url, json=payload, headers=headers)
        resp.raise_for_status()

    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    usage = data.get("usage", {})

    return content, usage


def _image_to_data_uri(path: Path) -> str | None:
    """读取图片文件并转为 data URI。"""
    try:
        mime_type = mimetypes.guess_type(str(path))[0] or "image/jpeg"
        raw = path.read_bytes()
        b64 = base64.b64encode(raw).decode("ascii")
        return f"data:{mime_type};base64,{b64}"
    except Exception as e:
        logger.warning("读取图片失败 %s: %s", path.name, e)
        return None


def parse_scoring_result(raw: str) -> dict[str, Any]:
    """解析模型返回的 JSON 评分结果（三级容错）。

    尝试1：直接 json.loads
    尝试2：提取 ```json ... ``` markdown 代码块
    尝试3：找第一个平衡括号 JSON 对象
    """
    raw = raw.strip()

    # 尝试1：直接解析
    try:
        result = json.loads(raw)
        return _safe_extract_penalized(result)
    except json.JSONDecodeError:
        pass

    # 尝试2：提取 markdown 代码块
    md_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", raw, re.DOTALL)
    if md_match:
        try:
            result = json.loads(md_match.group(1))
            return _safe_extract_penalized(result)
        except json.JSONDecodeError:
            pass

    # 尝试3：找第一个平衡括号 JSON 对象
    start = raw.find("{")
    if start >= 0:
        json_str = _extract_balanced_json(raw[start:])
        if json_str:
            try:
                result = json.loads(json_str)
                return _safe_extract_penalized(result)
            except json.JSONDecodeError:
                pass

    logger.error("无法解析美观度评分结果: %s", raw[:200])
    return {}


def _safe_extract_penalized(result: dict) -> dict:
    """安全提取 penalized_frames 字段（独立 try-except，防止该字段异常影响主评分）。"""
    try:
        pf = result.get("penalized_frames")
        if not isinstance(pf, list):
            result["penalized_frames"] = []
    except Exception:
        result["penalized_frames"] = []
    return result


def _extract_balanced_json(text: str) -> str | None:
    """从文本中提取第一个平衡括号的 JSON 对象。"""
    depth = 0
    in_string = False
    escape_next = False

    for i, ch in enumerate(text):
        if escape_next:
            escape_next = False
            continue
        if ch == "\\":
            if in_string:
                escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[: i + 1]

    return None


def filter_penalized_frames(penalized: list, scored_frames: list[str]) -> list:
    """过滤掉不在 scored_frames 中的 penalized_frames（防模型幻觉）。

    只保留 frame_path 在实际评分帧中能找到对应文件名的条目。
    """
    if not penalized or not scored_frames:
        return []

    # 构建已评分帧的文件名集合
    scored_basenames = {Path(f).name for f in scored_frames}

    filtered = []
    for item in penalized:
        if not isinstance(item, dict):
            continue
        frame_path = item.get("frame_path", "")
        # 归一化为文件名
        basename = Path(frame_path).name if frame_path else ""
        if basename in scored_basenames:
            filtered.append(item)

    return filtered
