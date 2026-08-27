"""截图提取器策略包

导出所有提取器类和注册表，供外部使用。
"""

from .base import BaseExtractor
from .file_extractor import FileExtractor
from .image_utils import decode_dimensions
from .midscene_extractor import MidsceneExtractor
from .playwright_extractor import PlaywrightExtractor
from .registry import ExtractorRegistry, default_registry

__all__ = [
    "BaseExtractor",
    "FileExtractor",
    "MidsceneExtractor",
    "PlaywrightExtractor",
    "ExtractorRegistry",
    "default_registry",
    "decode_dimensions",
]
