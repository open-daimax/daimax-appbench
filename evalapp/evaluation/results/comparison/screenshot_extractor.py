"""截图提取器 - 从E2E报告HTML中提取截图

顶层公共模块，保持外部 API 不变。
内部提取逻辑委托给 extractors/ 子包的策略模式实现。
"""

import base64
import logging
import re
import struct
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# 最小截图尺寸过滤 — 排除光标、加载动画等小图标
_MIN_WIDTH = 200
_MIN_HEIGHT = 200

from .extractors import default_registry

# 已知生成器名称，用于回退搜索 {generator}/{sample_id}/ 目录结构
KNOWN_GENERATORS = ["claude", "codeflying"]


def _get_image_dimensions(img_bytes: bytes, img_format: str) -> tuple[int, int]:
    """从图片原始字节中解析宽高，失败返回 (0, 0)。

    PNG: 读取 IHDR chunk（偏移 16-23）。
    JPEG: 查找 SOF0/SOF1/SOF2 标记。
    """
    try:
        if img_format == 'png' and img_bytes[:4] == b'\x89PNG':
            w, h = struct.unpack('>II', img_bytes[16:24])
            return w, h
        elif img_format == 'jpeg' and img_bytes[:2] == b'\xff\xd8':
            j = 2
            while j < min(len(img_bytes), 2000):
                if img_bytes[j] == 0xFF and img_bytes[j + 1] in (0xC0, 0xC1, 0xC2):
                    h, w = struct.unpack('>HH', img_bytes[j + 5:j + 9])
                    return w, h
                j += 1
    except Exception:
        pass
    return 0, 0


def _is_valid_mobile_screenshot(img_bytes: bytes, img_format: str, platform: str) -> bool:
    """判断图片是否为有效的手机截图。

    规则：
      - 最小尺寸检查：宽度 >= _MIN_WIDTH 且 高度 >= _MIN_HEIGHT
      - 对于 android/ios/miniprogram 平台：宽度 > 1000px 且横屏(h<=w)时过滤
        （与提取器内部规则一致，避免小尺寸接近正方形图片被误判）
      - 对于其他平台：只做最小尺寸检查

    Args:
        img_bytes: 图片原始字节
        img_format: 图片格式 ('jpeg' 或 'png')
        platform: 平台标识 ('android', 'ios', 'miniprogram' 等)

    Returns:
        True 表示有效截图，False 表示应被过滤
    """
    w, h = _get_image_dimensions(img_bytes, img_format)
    if w == 0 and h == 0:
        logger.debug("截图尺寸解析失败，保留: format=%s", img_format)
        return True  # 无法解析尺寸时不做过滤，保留图片

    # 最小尺寸检查
    if w < _MIN_WIDTH or h < _MIN_HEIGHT:
        logger.info(
            "过滤小图标截图: %dx%d (最小要求 %dx%d), platform=%s",
            w, h, _MIN_WIDTH, _MIN_HEIGHT, platform,
        )
        return False

    # 移动平台（android/ios/miniprogram）：横屏检查
    # 统一规则：仅当宽度 > 1000px 且为横屏时才过滤（与提取器内部规则一致）
    # 这避免了将接近正方形的小尺寸截图误判为横屏
    if platform in ("android", "ios", "miniprogram") and w > 1000 and h <= w:
        logger.info(
            "过滤横屏截图(非手机截图): %dx%d, platform=%s",
            w, h, platform,
        )
        return False

    return True


def extract_first_screenshot_data_url(html_path: Path) -> Optional[str]:
    """
    从E2E报告HTML中提取第一张截图的data URL

    Args:
        html_path: E2E报告HTML文件路径

    Returns:
        data URL字符串 (如 "data:image/jpeg;base64,...") 或 None
    """
    return default_registry.extract_first(html_path)


def extract_last_screenshot_data_url(html_path: Path) -> Optional[str]:
    """从E2E报告HTML中提取最后一张有效截图的data URL。

    用于 TC_LAUNCH 等场景：测试用例通过时，最后一帧是应用渲染
    完成后的最终状态，可避免取到启动阶段的瞬时白屏帧。

    Args:
        html_path: E2E报告HTML文件路径

    Returns:
        data URL字符串 (如 "data:image/jpeg;base64,...") 或 None
    """
    all_screenshots = default_registry.extract_all(html_path)
    if all_screenshots:
        # 取最后一张（应用渲染完成的最终状态）
        return all_screenshots[-1].get("url")
    return None


def _find_report_in_generator_dir(generator_dir: Path) -> Optional[Path]:
    """
    在生成器目录下查找报告HTML文件。
    搜索顺序与 evaluator.py 中报告路径查找逻辑一致：
      1. report_dir / "report.html"
      2. report_dir / ".test_intermediates/ai-ui-test" 下最新的 report.html
      3. report_dir / "midscene_run/report" 下 playwright-*.html

    Args:
        generator_dir: 生成器目录，如 e2e_reports/{generator}/HappyMatch

    Returns:
        report.html路径或None
    """
    if not generator_dir.is_dir():
        return None

    # 1. 根目录 report.html
    report_html = generator_dir / "report.html"
    if report_html.exists():
        return report_html

    # 2. .test_intermediates/ai-ui-test/*/report.html（取最新的）
    test_intermediates_dir = generator_dir / ".test_intermediates" / "ai-ui-test"
    if test_intermediates_dir.exists():
        html_files = list(test_intermediates_dir.glob("*/report.html"))
        if html_files:
            html_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            return html_files[0]

    # 3. midscene_run/report/playwright-*.html
    midscene_report_dir = generator_dir / "midscene_run" / "report"
    if midscene_report_dir.exists():
        html_files = list(midscene_report_dir.glob("playwright-*.html"))
        if html_files:
            html_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            return html_files[0]

    # 4. 兜底：搜索目录下任意 .html 文件
    html_files = list(generator_dir.glob("*.html"))
    if html_files:
        return html_files[0]

    return None


def _find_all_reports_in_generator_dir(generator_dir: Path) -> list[Path]:
    """
    在生成器目录下查找所有报告HTML文件。

    Args:
        generator_dir: 生成器目录，如 e2e_reports/{generator}/HappyMatch

    Returns:
        报告HTML文件路径列表
    """
    if not generator_dir.is_dir():
        return []

    reports = []

    # 根目录 report.html
    report_html = generator_dir / "report.html"
    if report_html.exists():
        reports.append(report_html)

    # .test_intermediates/ai-ui-test/*/report.html
    test_intermediates_dir = generator_dir / ".test_intermediates" / "ai-ui-test"
    if test_intermediates_dir.exists():
        for html_file in test_intermediates_dir.glob("*/report.html"):
            if html_file not in reports:
                reports.append(html_file)

    # midscene_run/report/playwright-*.html
    midscene_report_dir = generator_dir / "midscene_run" / "report"
    if midscene_report_dir.exists():
        for html_file in midscene_report_dir.glob("playwright-*.html"):
            if html_file not in reports:
                reports.append(html_file)

    return reports


def find_launch_report(e2e_reports_dir: Path, sample_id: str, platform: str) -> Optional[Path]:
    """
    查找TC_LAUNCH或TC001的report.html

    Args:
        e2e_reports_dir: E2E报告根目录
        sample_id: 样本ID (如 "HappyMatch")
        platform: 平台 (如 "android", "ios", "miniprogram")

    Returns:
        report.html路径或None

    优先级:
        1. {sample_id}_{platform}_TC_LAUNCH_*/report.html（小程序导出格式）
        2. {sample_id}_{platform}_TC001_*/report.html（小程序导出格式）
        3. {generator}/{sample_id}/ 下的报告（iOS/Android等平台格式）
    """
    # 策略1：小程序扁平目录模式 {sample_id}_{platform}_TC_LAUNCH_*/report.html
    launch_patterns = [
        f"{sample_id}_{platform}_TC_LAUNCH_*",
        f"{sample_id}_{platform}_TC001_*",
    ]

    for pattern in launch_patterns:
        matches = list(e2e_reports_dir.glob(pattern))
        if matches:
            # 查找目录中的HTML文件（可能是report.html或其他命名）
            report_dir = matches[0]
            html_files = list(report_dir.glob("*.html"))
            if html_files:
                return html_files[0]  # 返回找到的第一个HTML文件

    # 策略2：遍历已知生成器目录 {generator}/{sample_id}/
    for gen_name in KNOWN_GENERATORS:
        generator_dir = e2e_reports_dir / gen_name / sample_id
        report = _find_report_in_generator_dir(generator_dir)
        if report:
            return report

    # 策略3：遍历所有子目录，查找 {any}/{sample_id}/ 结构
    if e2e_reports_dir.is_dir():
        for entry in e2e_reports_dir.iterdir():
            if entry.is_dir() and entry.name not in KNOWN_GENERATORS:
                generator_dir = entry / sample_id
                report = _find_report_in_generator_dir(generator_dir)
                if report:
                    return report

    return None


def extract_all_screenshots(html_path: Path) -> list[dict]:
    """
    从E2E报告HTML中提取所有截图(排除SVG)。

    委托给策略模式提取器自动检测文件格式并提取。

    Args:
        html_path: E2E报告HTML文件路径

    Returns:
        list of dict: [{"url": "data:image/jpeg;base64,...", "step_name": "step_1"}, ...]
    """
    return default_registry.extract_all(html_path)


def save_all_screenshots(
    html_path: Path, output_dir: Path = None, platform: str = "",
) -> list[Path]:
    """提取并保存所有截图为文件到磁盘。

    Args:
        html_path: E2E报告HTML文件路径
        output_dir: 输出目录，默认为html_path同级的screenshots目录
        platform: 平台标识 ('android', 'ios', 'miniprogram' 等)，用于过滤非手机截图

    Returns:
        保存的文件路径列表
    """
    screenshots = extract_all_screenshots(html_path)
    if not screenshots:
        return []

    if output_dir is None:
        output_dir = html_path.parent / "screenshots"
    output_dir.mkdir(parents=True, exist_ok=True)

    saved_paths = []
    for shot in screenshots:
        step_name = shot["step_name"]
        url = shot["url"]

        # 从 data URL 解析格式和数据
        # 格式: data:image/(jpeg|png);base64,<data>
        header, b64_data = url.split(",", 1)
        # 提取图片格式: jpeg 或 png
        fmt = header.split("/")[1].split(";")[0]
        ext = "jpg" if fmt == "jpeg" else fmt

        # 优先使用缓存的解码字节（由 _filter_screenshots 缓存），避免重复解码
        img_bytes = shot.get("_img_bytes") or base64.b64decode(b64_data)

        # 过滤无效截图
        if platform and not _is_valid_mobile_screenshot(img_bytes, fmt, platform):
            continue

        file_path = output_dir / f"{step_name}.{ext}"
        file_path.write_bytes(img_bytes)
        saved_paths.append(file_path)

    return saved_paths


def _filter_screenshots(screenshots: list[dict], platform: str) -> list[dict]:
    """过滤无效截图（小图标、横屏非手机截图等）。

    对 screenshots 列表中的每张截图解码并调用 _is_valid_mobile_screenshot 判断。
    解码失败时保留截图（避免误丢数据）。
    解码后的 img_bytes 缓存到 shot["_img_bytes"] 中，供后续保存时直接使用，避免二次解码。
    """
    if not platform or not screenshots:
        return screenshots

    filtered = []
    for shot in screenshots:
        url = shot["url"]
        try:
            header, b64_data = url.split(",", 1)
            fmt = header.split("/")[1].split(";")[0]
            img_bytes = base64.b64decode(b64_data)
        except (ValueError, IndexError):
            filtered.append(shot)  # 解析失败时保留
            continue

        if _is_valid_mobile_screenshot(img_bytes, fmt, platform):
            # 缓存解码后的字节，避免后续 save 时重复解码
            shot["_img_bytes"] = img_bytes
            filtered.append(shot)

    from .phash_dedup import deduplicate_screenshots
    filtered = deduplicate_screenshots(filtered, threshold=5)
    return filtered


def extract_sample_all_screenshots(
    e2e_reports_dir: Path, sample_id: str, platform: str,
    tc_ids: list[str] | None = None,
) -> list[dict]:
    """
    提取样本所有测试用例的全部截图。
    遍历所有 {sample_id}_{platform}_* 目录，提取每个用例的所有截图。
    如果扁平目录未找到，回退到 {generator}/{sample_id}/ 目录结构。

    Args:
        e2e_reports_dir: E2E报告根目录
        sample_id: 样本ID (如 "HappyMatch")
        platform: 平台 (如 "android", "ios", "miniprogram")
        tc_ids: 可选，测试用例ID列表，用于将多个报告文件按顺序分配给各TC。

    Returns:
        list of dict: [{"url": "...", "step_name": "TC_LAUNCH_step_1"}, ...]
    """
    if not e2e_reports_dir.exists():
        return []

    all_screenshots = []

    # 策略0（新）：样本级目录结构，目录名不含 sample_id 前缀
    # 适用场景：e2e_reports_dir 是 workspace/{sample_id}/e2e_reports
    # 目录格式：{platform}_TC_LAUNCH_* 或 {platform}_TC001_* 等
    sample_tc_pattern = f"{platform}_TC_*"
    sample_tc_dirs = sorted(e2e_reports_dir.glob(sample_tc_pattern))

    if sample_tc_dirs:
        for tc_dir in sample_tc_dirs:
            dir_name = tc_dir.name
            remaining = dir_name.removeprefix(f"{platform}_")
            ts_match = re.match(r'(.+?)_\d{8}_\d{6}$', remaining)
            tc_id = ts_match.group(1) if ts_match else remaining

            html_files = list(tc_dir.glob("*.html"))
            if not html_files:
                continue

            screenshots = extract_all_screenshots(html_files[0])
            for shot in screenshots:
                original_step = shot["step_name"]
                step_num = original_step.split("_")[1] if "_" in original_step else original_step
                all_screenshots.append({
                    "url": shot["url"],
                    "step_name": f"{tc_id}_step_{step_num}"
                })
        return _filter_screenshots(all_screenshots, platform)

    # 策略1：小程序扁平目录模式 {sample_id}_{platform}_*
    pattern = f"{sample_id}_{platform}_*"
    tc_dirs = sorted(e2e_reports_dir.glob(pattern))

    for tc_dir in tc_dirs:
        # 从目录名提取TC_ID (如 TC_LAUNCH, TC001 等)
        # 目录名格式: {sample_id}_{platform}_{TC_ID}_{timestamp}
        dir_name = tc_dir.name
        remaining = dir_name.removeprefix(f"{sample_id}_{platform}_")
        # 去掉末尾时间戳 (_YYYYMMDD_HHMMSS)
        ts_match = re.match(r'(.+?)_\d{8}_\d{6}$', remaining)
        tc_id = ts_match.group(1) if ts_match else remaining

        # 查找目录中的HTML文件
        html_files = list(tc_dir.glob("*.html"))
        if not html_files:
            continue

        # 提取该测试用例的所有截图
        screenshots = extract_all_screenshots(html_files[0])
        for shot in screenshots:
            # 重命名step_name为 TC_ID_step_N 格式
            original_step = shot["step_name"]  # step_1, step_2, ...
            step_num = original_step.split("_")[1] if "_" in original_step else original_step
            all_screenshots.append({
                "url": shot["url"],
                "step_name": f"{tc_id}_step_{step_num}"
            })

    # 如果扁平目录找到了截图，统一过滤后返回
    if all_screenshots:
        return _filter_screenshots(all_screenshots, platform)

    # 策略2：miniprogram 平台 — 多个 playwright-*.html 分别对应不同 TC
    # 报告路径: {generator}/{sample_id}/midscene_run/report/playwright-*.html
    for gen_name in KNOWN_GENERATORS:
        midscene_dir = e2e_reports_dir / gen_name / sample_id / "midscene_run" / "report"
        if midscene_dir.is_dir():
            playwright_files = sorted(
                midscene_dir.glob("playwright-*.html"),
                key=lambda p: p.stat().st_mtime,
            )
            if playwright_files and tc_ids:
                # 按时间顺序将报告分配给各 TC
                for idx, report_path in enumerate(playwright_files):
                    tc_id = tc_ids[idx] if idx < len(tc_ids) else f"TC_UNKNOWN_{idx}"
                    screenshots = extract_all_screenshots(report_path)
                    for shot in screenshots:
                        original_step = shot["step_name"]
                        step_num = original_step.split("_")[1] if "_" in original_step else original_step
                        all_screenshots.append({
                            "url": shot["url"],
                            "step_name": f"{tc_id}_step_{step_num}"
                        })
                return _filter_screenshots(all_screenshots, platform)

    # 策略3：遍历已知生成器目录 {generator}/{sample_id}/
    for gen_name in KNOWN_GENERATORS:
        generator_dir = e2e_reports_dir / gen_name / sample_id
        reports = _find_all_reports_in_generator_dir(generator_dir)
        for report_path in reports:
            screenshots = extract_all_screenshots(report_path)
            for i, shot in enumerate(screenshots, start=1):
                all_screenshots.append({
                    "url": shot["url"],
                    "step_name": f"{gen_name}_step_{i}"
                })

    # 策略4：遍历所有子目录，查找 {any}/{sample_id}/ 结构
    if not all_screenshots and e2e_reports_dir.is_dir():
        for entry in e2e_reports_dir.iterdir():
            if entry.is_dir() and entry.name not in KNOWN_GENERATORS:
                generator_dir = entry / sample_id
                reports = _find_all_reports_in_generator_dir(generator_dir)
                for report_path in reports:
                    screenshots = extract_all_screenshots(report_path)
                    for i, shot in enumerate(screenshots, start=1):
                        all_screenshots.append({
                            "url": shot["url"],
                            "step_name": f"{entry.name}_step_{i}"
                        })

    return _filter_screenshots(all_screenshots, platform)


def extract_sample_screenshot(
    e2e_reports_dir: Path, 
    sample_id: str, 
    platform: str
) -> dict:
    """
    提取样本的截图
    
    Args:
        e2e_reports_dir: E2E报告根目录
        sample_id: 样本ID
        platform: 平台
        
    Returns:
        {
            "screenshot": "data:image/jpeg;base64,...",  # 或 None
            "source": "TC_LAUNCH" | "TC001" | "generator_dir" | None,
            "reason": "说明"
        }
    
    搜索策略（按优先级）:
        1. {sample_id}_{platform}_TC_LAUNCH_*（小程序导出格式）
        2. {sample_id}_{platform}_TC001_*（小程序导出格式）
        3. {generator}/{sample_id}/ 下的报告（iOS/Android等平台格式）
    """
    if not e2e_reports_dir.exists():
        return {
            "screenshot": None,
            "source": None,
            "reason": "E2E报告目录不存在"
        }
    
    # 策略0（新）：样本级目录结构，目录名不含 sample_id 前缀
    # 适用场景：e2e_reports_dir 是 workspace/{sample_id}/e2e_reports
    # 目录格式：{platform}_TC_LAUNCH_* 或 {platform}_TC001_*
    # 注意：TC_LAUNCH 优先取最后一帧（应用渲染完成状态），避免取到启动白屏帧
    launch_pattern = f"{platform}_TC_LAUNCH_*"
    launch_dirs = sorted(e2e_reports_dir.glob(launch_pattern), reverse=True)
    
    if launch_dirs:
        html_files = list(launch_dirs[0].glob("*.html"))
        if html_files:
            # 优先取最后一帧（渲染完成的最终状态），回退到第一帧
            screenshot = extract_last_screenshot_data_url(html_files[0])
            if not screenshot:
                screenshot = extract_first_screenshot_data_url(html_files[0])
            if screenshot:
                return {
                    "screenshot": screenshot,
                    "source": "TC_LAUNCH",
                    "reason": f"来自 {launch_dirs[0].name}"
                }
    
    tc001_pattern = f"{platform}_TC001_*"
    tc001_dirs = sorted(e2e_reports_dir.glob(tc001_pattern), reverse=True)
    
    if tc001_dirs:
        html_files = list(tc001_dirs[0].glob("*.html"))
        if html_files:
            screenshot = extract_first_screenshot_data_url(html_files[0])
            if screenshot:
                return {
                    "screenshot": screenshot,
                    "source": "TC001",
                    "reason": f"来自 {tc001_dirs[0].name} (TC_LAUNCH不存在)"
                }
    
    # 策略1：小程序扁平目录 - 查找TC_LAUNCH
    # 同样优先取最后一帧，避免启动白屏
    launch_pattern = f"{sample_id}_{platform}_TC_LAUNCH_*"
    launch_dirs = list(e2e_reports_dir.glob(launch_pattern))
    
    if launch_dirs:
        # 查找HTML文件
        html_files = list(launch_dirs[0].glob("*.html"))
        if html_files:
            screenshot = extract_last_screenshot_data_url(html_files[0])
            if not screenshot:
                screenshot = extract_first_screenshot_data_url(html_files[0])
            if screenshot:
                return {
                    "screenshot": screenshot,
                    "source": "TC_LAUNCH",
                    "reason": f"来自 {launch_dirs[0].name}"
                }
    
    # 策略2：小程序扁平目录 - 回退到TC001
    tc001_pattern = f"{sample_id}_{platform}_TC001_*"
    tc001_dirs = list(e2e_reports_dir.glob(tc001_pattern))
    
    if tc001_dirs:
        html_files = list(tc001_dirs[0].glob("*.html"))
        if html_files:
            screenshot = extract_first_screenshot_data_url(html_files[0])
            if screenshot:
                return {
                    "screenshot": screenshot,
                    "source": "TC001",
                    "reason": f"来自 {tc001_dirs[0].name} (TC_LAUNCH不存在)"
                }
    
    # 策略3：遍历已知生成器目录 {generator}/{sample_id}/
    for gen_name in KNOWN_GENERATORS:
        generator_dir = e2e_reports_dir / gen_name / sample_id
        report = _find_report_in_generator_dir(generator_dir)
        if report:
            screenshot = extract_first_screenshot_data_url(report)
            if screenshot:
                return {
                    "screenshot": screenshot,
                    "source": "generator_dir",
                    "reason": f"来自 {gen_name}/{sample_id} ({report.relative_to(generator_dir)})"
                }
    
    # 策略4：遍历所有子目录，查找 {any}/{sample_id}/ 结构
    for entry in e2e_reports_dir.iterdir():
        if entry.is_dir() and entry.name not in KNOWN_GENERATORS:
            generator_dir = entry / sample_id
            report = _find_report_in_generator_dir(generator_dir)
            if report:
                screenshot = extract_first_screenshot_data_url(report)
                if screenshot:
                    return {
                        "screenshot": screenshot,
                        "source": "generator_dir",
                        "reason": f"来自 {entry.name}/{sample_id} ({report.relative_to(generator_dir)})"
                    }
    
    return {
        "screenshot": None,
        "source": None,
        "reason": f"未找到 {sample_id}_{platform} 的TC_LAUNCH或TC001报告，也未找到生成器目录报告"
    }


# ============== 提取结果缓存（基于文件路径 + mtime） ==============

_extraction_cache: dict[tuple[str, float], list[dict]] = {}
_CACHE_MAX_SIZE = 64


def _cached_extract_all(html_path: Path) -> list[dict]:
    """带缓存的截图提取，避免对同一文件重复提取。
    
    缓存键为 (file_path_str, mtime)，文件修改后自动失效。
    """
    try:
        stat = html_path.stat()
        cache_key = (str(html_path), stat.st_mtime)
    except OSError:
        return extract_all_screenshots(html_path)

    if cache_key in _extraction_cache:
        return _extraction_cache[cache_key]

    result = extract_all_screenshots(html_path)

    # 简单的 LRU 淮入策略
    if len(_extraction_cache) >= _CACHE_MAX_SIZE:
        # 删除最早插入的一半
        keys = list(_extraction_cache.keys())
        for k in keys[: _CACHE_MAX_SIZE // 2]:
            del _extraction_cache[k]

    _extraction_cache[cache_key] = result
    return result


# ============== 并发提取工具 ==============

def extract_multiple_reports_parallel(
    report_paths: list[Path],
    platform: str = "",
    max_workers: int = 4,
) -> list[dict]:
    """并发提取多个 HTML 报告中的截图。
    
    使用 ThreadPoolExecutor 并行处理多个 HTML 文件的提取，
    尤其适用于 _extract_and_save_screenshots 中多文件场景。
    
    Args:
        report_paths: 报告 HTML 文件路径列表
        platform: 平台标识，用于过滤
        max_workers: 最大并发线程数
    
    Returns:
        合并后的截图列表
    """
    if not report_paths:
        return []

    if len(report_paths) == 1:
        result = _cached_extract_all(report_paths[0])
        return _filter_screenshots(result, platform) if platform else result

    all_screenshots = []
    with ThreadPoolExecutor(max_workers=min(max_workers, len(report_paths))) as executor:
        future_to_path = {
            executor.submit(_cached_extract_all, path): path
            for path in report_paths
        }
        for future in as_completed(future_to_path):
            try:
                screenshots = future.result()
                all_screenshots.extend(screenshots)
            except Exception as e:
                path = future_to_path[future]
                logger.warning("并发提取截图失败 %s: %s", path, e)

    return _filter_screenshots(all_screenshots, platform) if platform else all_screenshots

    return _filter_screenshots(all_screenshots, platform) if platform else all_screenshots
