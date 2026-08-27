"""Midscene HTML 截图提取器

处理 Midscene E2E 报告（React SPA），截图以 Base64 格式嵌入 HTML 的 JavaScript 数据中。
步骤截图格式: data-id="UUID">data:image/(jpeg|png);base64,...
"""

import logging
import re
from pathlib import Path
from typing import Optional

from .base import BaseExtractor
from .image_utils import decode_dimensions

logger = logging.getLogger(__name__)

# Midscene SPA 中步骤截图的正则模式
# 匹配: data-id="UUID">data:image/(jpeg|png);base64,...
_MIDSCENE_STEP_PATTERN = re.compile(
    r'data-id="[^"]+">data:image/(jpeg|png);base64,([A-Za-z0-9+/=]+)'
)

# 最小截图尺寸，用于跳过 logo/图标等装饰性小图
_MIN_SCREENSHOT_DIM = 200

# Midscene 特征检测的快速探测字符串
_MIDSCENE_MARKER_DATA_ID = 'data-id="'
_MIDSCENE_MARKER_IMAGE = "data:image/"


class MidsceneExtractor(BaseExtractor):
    """Midscene HTML 报告截图提取器。

    从 Midscene E2E 报告 HTML 中提取嵌入的 Base64 截图。
    支持缓存 can_handle 读取的内容，避免 extract_all 重复读取同一文件。
    """

    def __init__(self):
        self._cached_path: Optional[Path] = None
        self._cached_content: Optional[str] = None

    def _read_content(self, path: Path) -> Optional[str]:
        """读取文件内容，带缓存（避免 can_handle + extract_all 两次读取）。"""
        if self._cached_path == path and self._cached_content is not None:
            return self._cached_content
        try:
            content = path.read_text(encoding="utf-8")
            self._cached_path = path
            self._cached_content = content
            return content
        except Exception:
            return None

    def can_handle(self, path: Path) -> bool:
        """判断文件是否为 Midscene 格式的 HTML 报告。

        检测条件：
          - 文件存在且为 .html 扩展名
          - 内容包含 Midscene 特征：data-id="..." 后跟 data:image

        优化：对大文件同时检查文件头部和尾部，解决截图数据在文件后部的漏检问题。
        """
        if not path.exists() or path.suffix.lower() != ".html":
            return False
        try:
            file_size = path.stat().st_size
            if file_size < 2 * 1024 * 1024:
                # 小文件直接全量读取，同时缓存供 extract_all 复用
                content = self._read_content(path)
                if content is None:
                    return False
                return _MIDSCENE_MARKER_DATA_ID in content and _MIDSCENE_MARKER_IMAGE in content
            else:
                # 大文件：检查文件头部 2MB + 尾部 2MB（解决截图在后部漏检问题）
                with open(path, 'r', encoding='utf-8') as f:
                    head = f.read(2 * 1024 * 1024)
                    if _MIDSCENE_MARKER_DATA_ID in head and _MIDSCENE_MARKER_IMAGE in head:
                        return True
                    # 读取尾部 2MB
                    f.seek(max(0, file_size - 2 * 1024 * 1024))
                    tail = f.read()
                    return _MIDSCENE_MARKER_DATA_ID in tail and _MIDSCENE_MARKER_IMAGE in tail
        except Exception:
            return False

    def extract_first(self, path: Path) -> Optional[str]:
        """提取第一张有效截图的 data URL（跳过 <200px 小图及 >1000px 桌面横屏截图）。"""
        if not path.exists():
            return None
        try:
            content = self._read_content(path)
            if content is None:
                return None
            for match in _MIDSCENE_STEP_PATTERN.finditer(content):
                img_format = match.group(1)
                base64_data = match.group(2)
                w, h = decode_dimensions(img_format, base64_data)
                # 跳过无法解析尺寸的图片（保守保留）
                if w == 0 and h == 0:
                    return f"data:image/{img_format};base64,{base64_data}"
                # 跳过装饰性小图
                if w < _MIN_SCREENSHOT_DIM or h < _MIN_SCREENSHOT_DIM:
                    continue
                # 跳过桌面级别横屏截图
                if w > 1000 and h <= w:
                    continue
                return f"data:image/{img_format};base64,{base64_data}"
            return None
        except Exception as e:
            logger.warning("[MidsceneExtractor] 提取截图失败 %s: %s", path, e)
            return None

    def extract_all(self, path: Path) -> list[dict]:
        """提取所有步骤截图（跳过 <200px 装饰性小图及 >1000px 桌面横屏截图）。"""
        if not path.exists():
            return []
        try:
            content = self._read_content(path)
            if content is None:
                return []
            matches = _MIDSCENE_STEP_PATTERN.findall(content)
            screenshots = []
            step_counter = 0
            for img_format, base64_data in matches:
                w, h = decode_dimensions(img_format, base64_data)
                # 跳过无法解析尺寸的图片（保守保留）
                if w == 0 and h == 0:
                    step_counter += 1
                    screenshots.append({
                        "url": f"data:image/{img_format};base64,{base64_data}",
                        "step_name": f"step_{step_counter}"
                    })
                    continue
                # 跳过装饰性小图
                if w < _MIN_SCREENSHOT_DIM or h < _MIN_SCREENSHOT_DIM:
                    continue
                # 跳过桌面级别横屏截图
                if w > 1000 and h <= w:
                    continue
                step_counter += 1
                screenshots.append({
                    "url": f"data:image/{img_format};base64,{base64_data}",
                    "step_name": f"step_{step_counter}"
                })
            return screenshots
        except Exception as e:
            logger.warning("[MidsceneExtractor] 提取截图失败 %s: %s", path, e)
            return []
