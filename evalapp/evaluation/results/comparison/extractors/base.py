"""截图提取器抽象基类"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional


class BaseExtractor(ABC):
    """截图提取器抽象基类，定义提取器接口。

    每种报告格式（Midscene、Playwright、独立文件等）实现各自的提取器子类，
    由 ExtractorRegistry 根据文件特征自动选择合适的提取器。
    """

    @abstractmethod
    def can_handle(self, path: Path) -> bool:
        """判断当前提取器是否能处理指定文件。

        Args:
            path: 文件路径

        Returns:
            True 表示可处理，False 表示不可处理
        """

    @abstractmethod
    def extract_first(self, path: Path) -> Optional[str]:
        """提取第一张截图的 data URL。

        Args:
            path: 报告文件路径

        Returns:
            data URL 字符串（如 "data:image/jpeg;base64,..."）或 None
        """

    @abstractmethod
    def extract_all(self, path: Path) -> list[dict]:
        """提取所有截图。

        Args:
            path: 报告文件路径

        Returns:
            list of dict: [{"url": "data:image/...;base64,...", "step_name": "step_1"}, ...]
        """
