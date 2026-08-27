"""High-performance JSON IO helpers with optional orjson backend.

性能优化点：
- 优先使用 ``orjson``（约 3-5 倍编解码速度）；缺失时回退到标准库 ``json``。
- 提供 ``dumps`` / ``loads`` / ``read_json`` / ``write_json`` 统一接口，
  屏蔽两套 API 在 ``bytes`` / ``str`` 上的差异。
- ``write_json`` 内置 ``indent``、``ensure_ascii``、``default=str`` 兼容
  默认 ``json.dump(..., indent=2, ensure_ascii=False, default=str)`` 的输出
  行为，方便在调用方就地替换。

注意：``orjson`` 序列化默认返回 ``bytes``，因此 ``dumps`` / ``write_json``
始终以二进制管线写文件，避免 encode/decode 来回往返。
"""

from __future__ import annotations

import json as _stdjson
import os
from pathlib import Path
from typing import Any

try:
    import orjson as _orjson  # type: ignore
    HAS_ORJSON = True
except ImportError:  # pragma: no cover - 依赖缺失时回退
    _orjson = None  # type: ignore
    HAS_ORJSON = False


def _orjson_default(obj: Any) -> Any:
    """orjson 无法直接序列化的对象兜底为 ``str``，对齐标准库 ``default=str``。"""
    try:
        return str(obj)
    except Exception:  # pragma: no cover - 极端兜底
        return repr(obj)


def dumps(
    data: Any,
    *,
    indent: int | None = None,
    ensure_ascii: bool = False,
    sort_keys: bool = False,
) -> str:
    """序列化为 ``str``，签名兼容标准库 ``json.dumps``。"""
    if HAS_ORJSON and not ensure_ascii:
        opt = 0
        if indent and indent > 0:
            opt |= _orjson.OPT_INDENT_2  # orjson 仅支持 indent=2
        if sort_keys:
            opt |= _orjson.OPT_SORT_KEYS
        return _orjson.dumps(data, default=_orjson_default, option=opt).decode("utf-8")
    return _stdjson.dumps(
        data,
        indent=indent,
        ensure_ascii=ensure_ascii,
        sort_keys=sort_keys,
        default=str,
    )


def loads(data: str | bytes) -> Any:
    """反序列化，支持 ``str`` / ``bytes`` 入参。"""
    if HAS_ORJSON:
        if isinstance(data, str):
            data = data.encode("utf-8")
        return _orjson.loads(data)
    if isinstance(data, bytes):
        data = data.decode("utf-8")
    return _stdjson.loads(data)


def read_json(path: str | os.PathLike) -> Any:
    """从文件读取并反序列化 JSON。

    使用二进制读取并交给 ``orjson`` 直接解析，可比 ``json.load(open(...))``
    快 2-4 倍（视文件大小而定）。
    """
    p = Path(path)
    with open(p, "rb") as f:
        raw = f.read()
    if not raw:
        return None
    return loads(raw)


def write_json(
    path: str | os.PathLike,
    data: Any,
    *,
    indent: int | None = 2,
    ensure_ascii: bool = False,
    sort_keys: bool = False,
) -> None:
    """序列化并写入文件，默认输出格式对齐 ``json.dump(..., indent=2, ensure_ascii=False)``。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if HAS_ORJSON and not ensure_ascii:
        opt = 0
        if indent and indent > 0:
            opt |= _orjson.OPT_INDENT_2
        if sort_keys:
            opt |= _orjson.OPT_SORT_KEYS
        with open(p, "wb") as f:
            f.write(_orjson.dumps(data, default=_orjson_default, option=opt))
        return
    with open(p, "w", encoding="utf-8") as f:
        _stdjson.dump(
            data,
            f,
            indent=indent,
            ensure_ascii=ensure_ascii,
            sort_keys=sort_keys,
            default=str,
        )


__all__ = [
    "HAS_ORJSON",
    "dumps",
    "loads",
    "read_json",
    "write_json",
]
