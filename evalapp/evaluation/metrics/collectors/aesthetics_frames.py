"""美观度评分 - 帧选取与去重模块。

从样本 screenshots/ 目录中选取关键帧用于美观度评分。
实现 pHash 感知哈希去重和均匀采样。
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from PIL import Image

logger = logging.getLogger(__name__)

# 支持的图片格式
_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
# 最大评分帧数
MAX_FRAMES = 10
# pHash 去重汉明距离阈值
DEDUP_THRESHOLD = 5


def select_key_frames(sample_dir: str, platform: str) -> list[Path]:
    """选取关键帧用于美观度评分。
    
    优先级：step_* > {platform}_*（排除launch_）> launch_{platform}.*
    流程：筛选 → 排序 → 去重 → 采样
    """
    screenshots_dir = Path(sample_dir) / "screenshots"
    if not screenshots_dir.is_dir():
        return []

    # 收集所有图片
    all_images = [
        f for f in screenshots_dir.iterdir()
        if f.is_file() and f.suffix.lower() in _IMAGE_SUFFIXES
    ]
    if not all_images:
        return []

    # 优先级筛选
    # 第一优先：step_* 文件
    step_frames = [f for f in all_images if f.name.startswith("step_")]
    if step_frames:
        frames = step_frames
    else:
        # 第二回退：{platform}_* 前缀（排除 launch_ 前缀）
        platform_frames = [
            f for f in all_images
            if f.name.startswith(f"{platform}_") and not f.name.startswith("launch_")
        ]
        if platform_frames:
            frames = platform_frames
        else:
            # 第三降级：单帧 launch_{platform}.*
            launch_frames = [
                f for f in all_images
                if f.name.startswith(f"launch_{platform}.")
            ]
            if launch_frames:
                return launch_frames[:1]  # 只取一帧
            return []

    # 按文件名末尾数字排序
    frames.sort(key=_extract_sort_key)

    # pHash 去重
    frames = deduplicate_frames(frames, threshold=DEDUP_THRESHOLD)

    # 超过 MAX_FRAMES 则均匀采样
    if len(frames) > MAX_FRAMES:
        frames = uniform_sample(frames, MAX_FRAMES)

    return frames


def _extract_sort_key(path: Path) -> int:
    """提取文件名 stem 中最后出现的数字作为排序 key。"""
    numbers = re.findall(r"\d+", path.stem)
    return int(numbers[-1]) if numbers else 0


def deduplicate_frames(paths: list[Path], threshold: int = DEDUP_THRESHOLD) -> list[Path]:
    """使用 pHash 感知哈希去重。
    
    汉明距离 <= threshold 视为重复帧。
    解码失败的帧直接保留（兜底策略）。
    """
    if len(paths) <= 1:
        return list(paths)

    kept: list[Path] = []
    kept_hashes: list[int] = []

    for path in paths:
        h = _compute_phash(path)
        if h is None:
            # 解码失败，直接保留
            kept.append(path)
            continue

        # 与所有已保留帧比较
        is_dup = False
        for kh in kept_hashes:
            if _hamming_distance(h, kh) <= threshold:
                is_dup = True
                break

        if not is_dup:
            kept.append(path)
            kept_hashes.append(h)

    return kept


def uniform_sample(paths: list[Path], max_frames: int = MAX_FRAMES) -> list[Path]:
    """均匀采样，保证包含首尾帧。
    
    算法：step = (len-1) / (max_frames-1)，取 round(i*step) 位置。
    """
    n = len(paths)
    if n <= max_frames:
        return list(paths)

    step = (n - 1) / (max_frames - 1)
    result: list[Path] = []
    seen: set[int] = set()

    for i in range(max_frames):
        idx = int(i * step + 0.5)
        if idx not in seen:
            seen.add(idx)
            result.append(paths[idx])

    return result


def _compute_phash(path: Path) -> int | None:
    """计算图片的感知哈希（pHash）。
    
    8x8 NEAREST 缩放 → BT.601 灰度 → 64bit 均值哈希。
    """
    try:
        with Image.open(path) as img:
            # 缩放到 8x8，最近邻插值
            small = img.resize((8, 8), Image.Resampling.NEAREST)
            # 转灰度（Pillow 的 .convert('L') 使用 ITU-R 601-2 luma）
            gray = small.convert("L")
            pixels = list(gray.getdata())

        # 计算均值
        avg = sum(pixels) / 64.0

        # 生成 64-bit 指纹
        hash_val = 0
        for i, px in enumerate(pixels):
            if px > avg:
                hash_val |= 1 << i

        return hash_val
    except Exception as e:
        logger.warning("pHash 计算失败 %s: %s", path.name, e)
        return None


def _hamming_distance(a: int, b: int) -> int:
    """计算两个 64-bit 哈希的汉明距离。"""
    return bin(a ^ b).count("1")
