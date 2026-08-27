"""pHash 感知哈希去重模块。

与 BenchEvalAgent Go 端 aesthetics/dedup.go 算法一致：
- 图片缩放到 8x8 灰度
- 计算平均亮度生成 64bit 指纹
- 汉明距离 <= threshold 视为视觉重复
"""

from __future__ import annotations

import base64
import io
import logging

from PIL import Image

logger = logging.getLogger(__name__)


def phash_from_bytes(img_bytes: bytes) -> int:
    """计算图片字节的感知哈希（64bit 指纹）。

    算法：解码 -> 缩放到 8x8 灰度 -> 计算像素均值 -> 高于均值为1，低于为0。
    返回 0 表示解码失败（该图不参与去重比较）。
    """
    try:
        img = Image.open(io.BytesIO(img_bytes))
        # 缩放到 8x8 灰度（最近邻插值，与 Go 端一致）
        img = img.convert("L").resize((8, 8), Image.NEAREST)
        pixels = list(img.getdata())
        avg = sum(pixels) / len(pixels)
        # 生成 64bit 指纹
        hash_val = 0
        for i, px in enumerate(pixels):
            if px >= avg:
                hash_val |= (1 << (63 - i))
        return hash_val
    except Exception as e:
        logger.debug("pHash 计算失败: %s", e)
        return 0


def hamming_distance(a: int, b: int) -> int:
    """计算两个 64bit 哈希的汉明距离。"""
    return bin(a ^ b).count("1")


def _get_hash(shot: dict) -> int:
    """从截图 dict 获取图片字节并计算 pHash。

    优先使用 '_img_bytes' 缓存，否则从 'url'（base64 data URL）解码。
    返回 0 表示无法获取或计算失败。
    """
    img_bytes = shot.get("_img_bytes")
    if img_bytes is None:
        url = shot.get("url", "")
        try:
            _, b64_data = url.split(",", 1)
            img_bytes = base64.b64decode(b64_data)
        except (ValueError, IndexError):
            return 0
    return phash_from_bytes(img_bytes)


def deduplicate_screenshots(screenshots: list[dict], threshold: int = 5) -> list[dict]:
    """顺序去重：仅与前一个保留帧比较，移除连续相似的截图。

    截图按步骤顺序排列，只移除连续重复帧（如 step 3 和 step 4 完全一样）。
    不同位置出现的相似帧（如 step 1 和 step 5 回到同一页面）会被保留，
    因为它们代表测试流程中不同的节点。

    截图 dict 中优先使用 '_img_bytes' 缓存（由 _filter_screenshots 提供），
    否则从 'url' 字段（base64 data URL）解码。

    Args:
        screenshots: 截图列表，每项为 {"url": "data:image/...;base64,...", "step_name": "...", "_img_bytes"?: bytes}
        threshold: 汉明距离阈值，默认 5（与 Go 端一致）

    Returns:
        去重后的截图列表（保持原始顺序）
    """
    if not screenshots:
        return screenshots

    result: list[dict] = [screenshots[0]]
    last_hash: int = _get_hash(screenshots[0])

    for i in range(1, len(screenshots)):
        current_hash = _get_hash(screenshots[i])
        if current_hash == 0:
            # 无法计算 hash 的直接保留，last_hash 不更新
            result.append(screenshots[i])
            continue
        if last_hash == 0 or hamming_distance(last_hash, current_hash) > threshold:
            result.append(screenshots[i])
            last_hash = current_hash
        # else: 与前一个保留帧相似，跳过

    if len(result) < len(screenshots):
        logger.info("pHash 顺序去重: %d → %d 张截图", len(screenshots), len(result))

    return result
