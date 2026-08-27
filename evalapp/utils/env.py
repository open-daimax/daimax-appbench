"""集中定义 EvalApp 使用的环境变量名与默认值。

每个常量是一个 ``(name, default)`` 元组：

    EVALAPP_WORKERS = ("EVALAPP_WORKERS", "4")

通过 :func:`get_env` 读取实际取值，避免在业务代码中散落
``os.environ.get("EVALAPP_*", "...")`` 这样的硬编码字面量。
"""

from __future__ import annotations

import os

# ---------------------------------------------------------------------------
# 后端服务（uvicorn）部署相关
# ---------------------------------------------------------------------------
EVALAPP_BACKEND_PORT = ("EVALAPP_BACKEND_PORT", "8000")
EVALAPP_BACKEND_WORKERS = ("EVALAPP_BACKEND_WORKERS", "1")
EVALAPP_BACKEND_LOG_LEVEL = ("EVALAPP_BACKEND_LOG_LEVEL", "info")
EVALAPP_FRONTEND_PORT = ("EVALAPP_FRONTEND_PORT", "3000")

# CORS 允许来源（逗号分隔），仅在显式列出时启用 credentials
EVALAPP_ALLOWED_ORIGINS = (
    "EVALAPP_ALLOWED_ORIGINS",
    "*",
)

# ---------------------------------------------------------------------------
# 评测执行运行时
# ---------------------------------------------------------------------------
# 并发 E2E 测试时最大模拟器/设备实例数（硬上限 4）
EVALAPP_MAX_DEVICES = ("EVALAPP_MAX_DEVICES", "4")

# 标记当前进程是否由 evalapp.web Task Runner 拉起（仅作为开关，无默认实义）
EVALAPP_TASK_RUNNER = ("EVALAPP_TASK_RUNNER", "")


def get_env(var: tuple[str, str], default: str | None = None) -> str:
    """读取环境变量。

    :param var: ``(name, default)`` 元组（建议使用本模块定义的常量）。
    :param default: 显式覆盖默认值；为 ``None`` 时使用元组自带默认值。
    """
    name, fallback = var
    if default is not None:
        fallback = default
    return os.environ.get(name, fallback)


def get_env_flag(var: tuple[str, str]) -> bool:
    """将环境变量解释为布尔开关：非空即 True。"""
    name, _ = var
    return bool(os.environ.get(name))


def get_env_int(var: tuple[str, str], default: int | None = None) -> int:
    """读取环境变量并转换为 ``int``，转换失败时回退到默认值。"""
    name, fallback = var
    raw = os.environ.get(name, fallback)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return int(fallback) if default is None else default
