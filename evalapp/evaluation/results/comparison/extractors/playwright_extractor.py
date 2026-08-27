"""Playwright HTML 截图提取器

处理 Playwright 原生报告 HTML（playwright-*.html），截图嵌入在报告的附件中。
"""

import logging
import mmap
import re
from pathlib import Path
from typing import Optional

from .base import BaseExtractor
from .image_utils import decode_dimensions

logger = logging.getLogger(__name__)

# Playwright 报告中截图附件的正则模式
# 匹配: data:image/(jpeg|png);base64,...
# Playwright 报告可能使用多种嵌入方式，此处匹配通用 data:image 模式
_PLAYWRIGHT_IMAGE_PATTERN = re.compile(
    r'data:image/(jpeg|png);base64,([A-Za-z0-9+/=]+)'
)

# 编译字节模式（用于 mmap 大文件搜索）
_PLAYWRIGHT_IMAGE_PATTERN_BYTES = re.compile(
    rb'data:image/(jpeg|png);base64,([A-Za-z0-9+/=]+)'
)

# 最小截图尺寸，用于跳过 logo/图标等装饰性小图
_MIN_SCREENSHOT_DIM = 200

# 超过此大小的文件使用 mmap 读取（10MB）
_LARGE_FILE_THRESHOLD = 10 * 1024 * 1024


class PlaywrightExtractor(BaseExtractor):
    """Playwright HTML 报告截图提取器。

    从 Playwright 原生报告 HTML 中提取嵌入的 Base64 截图。
    对大文件(>10MB)使用 mmap 优化内存占用。
    """

    def can_handle(self, path: Path) -> bool:
        """判断文件是否为 Playwright 格式的 HTML 报告。

        检测条件：
          - 文件名匹配 playwright-*.html 模式
        """
        if not path.exists() or path.suffix.lower() != ".html":
            return False
        return path.name.startswith("playwright-") and path.name.endswith(".html")

    def extract_first(self, path: Path) -> Optional[str]:
        """提取第一张有效截图的 data URL（跳过 <200px 的装饰性小图及 >1000px 的桌面截图）。"""
        if not path.exists():
            return None
        try:
            file_size = path.stat().st_size
            if file_size > _LARGE_FILE_THRESHOLD:
                return self._extract_first_mmap(path)

            content = path.read_text(encoding="utf-8")
            for match in _PLAYWRIGHT_IMAGE_PATTERN.finditer(content):
                img_format = match.group(1)
                base64_data = match.group(2)
                w, h = decode_dimensions(img_format, base64_data)
                if w == 0 and h == 0:
                    return f"data:image/{img_format};base64,{base64_data}"
                # 跳过装饰性小图
                if w < _MIN_SCREENSHOT_DIM or h < _MIN_SCREENSHOT_DIM:
                    continue
                # 跳过桌面级别横屏截图（宽度 > 1000px 且 横屏）
                if w > 1000 and h <= w:
                    continue
                return f"data:image/{img_format};base64,{base64_data}"
            return None
        except Exception as e:
            logger.warning("[PlaywrightExtractor] 提取截图失败 %s: %s", path, e)
            return None

    def _extract_first_mmap(self, path: Path) -> Optional[str]:
        """使用 mmap 从大文件中提取第一张截图，避免全量加载到内存。"""
        try:
            with open(path, 'rb') as f:
                with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                    for match in _PLAYWRIGHT_IMAGE_PATTERN_BYTES.finditer(mm):
                        img_format = match.group(1).decode('ascii')
                        base64_data = match.group(2).decode('ascii')
                        w, h = decode_dimensions(img_format, base64_data)
                        if w == 0 and h == 0:
                            return f"data:image/{img_format};base64,{base64_data}"
                        if w < _MIN_SCREENSHOT_DIM or h < _MIN_SCREENSHOT_DIM:
                            continue
                        if w > 1000 and h <= w:
                            continue
                        return f"data:image/{img_format};base64,{base64_data}"
            return None
        except Exception as e:
            logger.warning("[PlaywrightExtractor] mmap提取截图失败 %s: %s", path, e)
            return None

    def extract_all(self, path: Path) -> list[dict]:
        """提取所有步骤截图（跳过 <200px 装饰性小图及 >1000px 桌面横屏截图）。"""
        if not path.exists():
            return []
        try:
            file_size = path.stat().st_size
            if file_size > _LARGE_FILE_THRESHOLD:
                return self._extract_all_mmap(path)

            content = path.read_text(encoding="utf-8")
            matches = _PLAYWRIGHT_IMAGE_PATTERN.findall(content)
            return self._process_matches(matches)
        except Exception as e:
            logger.warning("[PlaywrightExtractor] 提取截图失败 %s: %s", path, e)
            return []

    def _extract_all_mmap(self, path: Path) -> list[dict]:
        """使用 mmap 从大文件中提取所有截图，避免全量加载到内存。"""
        try:
            matches = []
            with open(path, 'rb') as f:
                with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                    for match in _PLAYWRIGHT_IMAGE_PATTERN_BYTES.finditer(mm):
                        img_format = match.group(1).decode('ascii')
                        base64_data = match.group(2).decode('ascii')
                        matches.append((img_format, base64_data))
            return self._process_matches(matches)
        except Exception as e:
            logger.warning("[PlaywrightExtractor] mmap提取截图失败 %s: %s", path, e)
            return []

    def _process_matches(self, matches: list[tuple[str, str]]) -> list[dict]:
        """处理正则匹配结果，过滤并构建截图列表。"""
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
