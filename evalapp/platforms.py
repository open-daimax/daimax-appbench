"""CLI 平台别名 → 构建工具链平台标识映射。"""

from __future__ import annotations

PLATFORM_ALIAS: dict[str, str] = {
    "web": "expo_web",
    "android": "expo_android",
    "ios": "expo_ios",
}

PUBLIC_PLATFORMS = list(PLATFORM_ALIAS.keys())  # ["web", "android", "ios"]


def resolve_platform(value: str) -> str:
    """将 CLI 输入的平台别名转为构建工具链使用的平台标识。

    命中别名表则改写，未知值原样透传（便于直接传入工具链标识）。
    """
    return PLATFORM_ALIAS.get(value.lower(), value)
