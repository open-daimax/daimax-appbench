"""图片二进制解析工具

仅通过 struct 解析 header 获取图片尺寸，避免引入 PIL 等重依赖。
"""

import base64
import struct


def decode_dimensions(img_format: str, base64_data: str) -> tuple[int, int]:
    """从 base64 编码的图片数据中解析宽高。

    Args:
        img_format: 图片格式，"jpeg" 或 "png"。
        base64_data: base64 编码的图片字符串。

    Returns:
        (width, height) 元组，解析失败返回 (0, 0)。
    """
    try:
        # 只解码前 1024 bytes 以优化性能
        partial_b64 = base64_data[:1368]  # 1368 base64 chars ≈ 1024 bytes
        img_bytes = base64.b64decode(partial_b64 + "==")  # 补齐 padding

        if img_format == "png" and img_bytes[:4] == b"\x89PNG":
            w, h = struct.unpack(">II", img_bytes[16:24])
            return w, h

        if img_format == "jpeg" and img_bytes[:2] == b"\xff\xd8":
            j = 2
            while j < len(img_bytes) - 9:
                if img_bytes[j] != 0xFF:
                    break
                if img_bytes[j + 1] in (0xC0, 0xC1, 0xC2):
                    h, w = struct.unpack(">HH", img_bytes[j + 5 : j + 9])
                    return w, h
                # 跳过当前 marker 段
                length = struct.unpack(">H", img_bytes[j + 2 : j + 4])[0]
                j += 2 + length
    except Exception:
        pass

    return 0, 0
