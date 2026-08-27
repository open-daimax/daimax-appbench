"""独立图片文件截图提取器

直接读取 PNG/JPG 文件并转为 data URL。
当传入目录时，遍历目录下所有图片文件。
"""

import base64
import logging
from pathlib import Path
from typing import Optional

from .base import BaseExtractor

logger = logging.getLogger(__name__)

# 支持的图片扩展名 → MIME 类型映射
_IMAGE_EXTENSIONS = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


class FileExtractor(BaseExtractor):
    """独立图片文件截图提取器。

    直接读取 PNG/JPG/WEBP 文件内容并转为 data URL。
    当 path 是目录时，遍历目录下所有支持格式的图片文件。
    """

    def can_handle(self, path: Path) -> bool:
        """判断文件/目录是否为支持的图片格式。

        检测条件：
          - path 是目录且包含至少一个图片文件
          - 或 path 存在且扩展名为 .png / .jpg / .jpeg / .webp
        """
        if not path.exists():
            return False
        if path.is_dir():
            return any(
                f.suffix.lower() in _IMAGE_EXTENSIONS
                for f in path.iterdir() if f.is_file()
            )
        return path.suffix.lower() in _IMAGE_EXTENSIONS

    def extract_first(self, path: Path) -> Optional[str]:
        """读取图片文件并转为 data URL。如果是目录则取第一个图片。"""
        if not path.exists():
            return None
        try:
            if path.is_dir():
                # 目录模式：找第一个图片文件
                image_files = sorted(
                    (f for f in path.iterdir()
                     if f.is_file() and f.suffix.lower() in _IMAGE_EXTENSIONS),
                    key=lambda f: f.name,
                )
                if not image_files:
                    return None
                path = image_files[0]

            mime = _IMAGE_EXTENSIONS.get(path.suffix.lower())
            if not mime:
                return None
            data = path.read_bytes()
            b64 = base64.b64encode(data).decode("ascii")
            return f"data:{mime};base64,{b64}"
        except Exception as e:
            logger.warning("[FileExtractor] 提取截图失败 %s: %s", path, e)
            return None

    def extract_all(self, path: Path) -> list[dict]:
        """读取图片文件或遍历目录下所有图片文件，返回截图记录列表。"""
        if not path.exists():
            return []
        try:
            if path.is_dir():
                # 目录模式：遍历所有图片文件
                image_files = sorted(
                    (f for f in path.iterdir()
                     if f.is_file() and f.suffix.lower() in _IMAGE_EXTENSIONS),
                    key=lambda f: f.name,
                )
                screenshots = []
                for idx, img_file in enumerate(image_files, start=1):
                    mime = _IMAGE_EXTENSIONS.get(img_file.suffix.lower())
                    if not mime:
                        continue
                    data = img_file.read_bytes()
                    b64 = base64.b64encode(data).decode("ascii")
                    screenshots.append({
                        "url": f"data:{mime};base64,{b64}",
                        "step_name": f"step_{idx}",
                    })
                return screenshots
            else:
                # 单文件模式
                data_url = self.extract_first(path)
                if data_url:
                    return [{"url": data_url, "step_name": "step_1"}]
                return []
        except Exception as e:
            logger.warning("[FileExtractor] 提取截图失败 %s: %s", path, e)
            return []
