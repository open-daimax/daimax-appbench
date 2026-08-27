"""截图提取器注册表

根据文件类型和内容自动选择合适的提取器策略。
注册表按优先级顺序遍历所有已注册的提取器，返回第一个 can_handle 为 True 的提取器。
"""

from pathlib import Path
from typing import Optional

from .base import BaseExtractor
from .file_extractor import FileExtractor
from .midscene_extractor import MidsceneExtractor
from .playwright_extractor import PlaywrightExtractor


class ExtractorRegistry:
    """截图提取器注册表。

    管理所有提取器实例，按优先级顺序自动选择合适的提取器。

    默认优先级（从高到低）：
      1. PlaywrightExtractor  — playwright-*.html 文件名优先匹配
      2. MidsceneExtractor    — 含 Midscene 特征的 HTML
      3. FileExtractor        — 独立 PNG/JPG 文件

    PlaywrightExtractor 优先于 MidsceneExtractor 是因为：
    Playwright 报告的文件名有明确特征，应优先按文件名匹配；
    而 MidsceneExtractor 需要读取文件内容做特征检测，作为通用 HTML 回退。
    """

    def __init__(self, extractors: list[BaseExtractor] | None = None):
        if extractors is not None:
            self._extractors = list(extractors)
        else:
            # 默认提取器列表（按优先级排序）
            self._extractors = [
                PlaywrightExtractor(),
                MidsceneExtractor(),
                FileExtractor(),
            ]

    def register(self, extractor: BaseExtractor, priority: int | None = None) -> None:
        """注册一个新的提取器。

        Args:
            extractor: 提取器实例
            priority: 插入位置（0 为最高优先级），None 则追加到末尾
        """
        if priority is not None:
            self._extractors.insert(priority, extractor)
        else:
            self._extractors.append(extractor)

    def get_extractor(self, path: Path) -> Optional[BaseExtractor]:
        """根据文件特征自动选择合适的提取器。

        Args:
            path: 文件路径

        Returns:
            第一个 can_handle 为 True 的提取器，若无匹配则返回 None
        """
        for extractor in self._extractors:
            if extractor.can_handle(path):
                return extractor
        return None

    def extract_first(self, path: Path) -> Optional[str]:
        """便捷方法：自动选择提取器并提取第一张截图。

        Args:
            path: 文件路径

        Returns:
            data URL 字符串或 None
        """
        extractor = self.get_extractor(path)
        if extractor:
            return extractor.extract_first(path)
        return None

    def extract_all(self, path: Path) -> list[dict]:
        """便捷方法：自动选择提取器并提取所有截图。

        Args:
            path: 文件路径

        Returns:
            截图列表
        """
        extractor = self.get_extractor(path)
        if extractor:
            return extractor.extract_all(path)
        return []

    @property
    def extractors(self) -> list[BaseExtractor]:
        """返回已注册的提取器列表（只读）。"""
        return list(self._extractors)


# 全局默认注册表实例
default_registry = ExtractorRegistry()
