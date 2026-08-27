#!/usr/bin/env python3
"""
对所有工作区的所有样本重新进行美观度评分。

Usage:
    python scripts/rescore_aesthetics.py
    python scripts/rescore_aesthetics.py --workspace my_workspace
    python scripts/rescore_aesthetics.py --sample sample_001 --platform ios
    python scripts/rescore_aesthetics.py --dry-run
    python scripts/rescore_aesthetics.py --force --concurrency 4
"""

import argparse
import json
import logging
import os
import sys
import concurrent.futures
from pathlib import Path

# 将 evalapp 包加入搜索路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evalapp.evaluation.metrics.aesthetics import (
    load_aesthetics_rules,
    select_key_frames,
    score_aesthetics_with_ai,
)
from evalapp.workspace.paths import (
    EXPO_SHARED_DIR,
    is_expo_platform,
    load_workspace_platforms,
)
from evalapp.workspace.sample_data import read_scores, write_scores

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# 枚举样本时排除的目录名
EXCLUDED_DIRS = {
    "e2e_reports", "stability_logs", ".idea",
    "__pycache__", "runs", "report",
}

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 美观度规则路径
AESTHETICS_RULES_PATH = PROJECT_ROOT / "dataset" / "aesthetics_rules.yaml"


def get_eval_app_factory():
    env_val = os.environ.get("EVAL_APP_FACTORY", "")
    if env_val:
        return Path(env_val)
    return Path.home() / "eval_app_factory"


def is_valid_workspace(path):
    return path.is_dir() and (path / "meta.json").exists()


def enumerate_workspaces(factory_dir, workspace_filter=None):
    if not factory_dir.is_dir():
        logger.error("eval_app_factory 目录不存在: %s", factory_dir)
        return []
    workspaces = []
    for entry in sorted(factory_dir.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name.startswith("."):
            continue
        if workspace_filter and entry.name != workspace_filter:
            continue
        if is_valid_workspace(entry):
            workspaces.append(entry)
    return workspaces


def enumerate_samples(workspace_dir, sample_filter=None):
    samples = []
    for entry in sorted(workspace_dir.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name.startswith("."):
            continue
        if entry.name in EXCLUDED_DIRS:
            continue
        if sample_filter and entry.name != sample_filter:
            continue
        if (entry / "generated_projects").is_dir():
            samples.append(entry.name)
    return samples


def resolve_expo_platforms(workspace_dir):
    """将共享源码目录名 "expo" 还原为真实的派生平台名（如 expo_web）。

    优先读工作区 meta.json 的 platforms 数组；读不到时从工作区名推断
    （如 {generator}_expo_web_20260729_113905 → expo_web）。
    """
    expo_platforms = [
        p for p in load_workspace_platforms(workspace_dir) if is_expo_platform(p)
    ]
    if expo_platforms:
        return expo_platforms

    import re
    m = re.search(r"(expo_[a-z]+)", workspace_dir.name)
    if m:
        return [m.group(1)]

    logger.warning(
        "工作区 %s 无法确定 expo 派生平台，回退为目录名 'expo'",
        workspace_dir.name,
    )
    return [EXPO_SHARED_DIR]


def enumerate_platforms(workspace_dir, sample_id, platform_filter=None):
    generated_dir = workspace_dir / sample_id / "generated_projects"
    if not generated_dir.is_dir():
        return []
    platforms = []
    for entry in sorted(generated_dir.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name == EXPO_SHARED_DIR:
            # expo 目录为派生平台共享源码，还原为真实平台名（如 expo_web）
            resolved = resolve_expo_platforms(workspace_dir)
        else:
            resolved = [entry.name]
        for plat in resolved:
            if platform_filter and plat != platform_filter:
                continue
            platforms.append(plat)
    return platforms


def get_app_category(workspace_dir, sample_id):
    sample_dir = workspace_dir / sample_id

    sample_yaml_path = sample_dir / "sample.yaml"
    if sample_yaml_path.exists():
        try:
            import yaml
            data = yaml.safe_load(sample_yaml_path.read_text(encoding="utf-8"))
            if data and isinstance(data, dict):
                cat = data.get("sample_top_category", "")
                if cat:
                    return str(cat)
        except Exception as _e:
            print(f"⚠️  silent skip in {__file__}: {_e}")

    generation_path = sample_dir / "generation.json"
    if generation_path.exists():
        try:
            data = json.loads(generation_path.read_text(encoding="utf-8"))
            for field in ("sample_top_category", "app_category", "category"):
                val = data.get(field, "")
                if val:
                    return str(val)
                if isinstance(data.get("meta"), dict):
                    val = data["meta"].get(field, "")
                    if val:
                        return str(val)
        except Exception as _e:
            print(f"⚠️  silent skip in {__file__}: {_e}")

    return ""


def get_screenshots_dir(workspace_dir, sample_id, platform):
    sample_dir = workspace_dir / sample_id
    screenshots_dir = sample_dir / "generated_projects" / platform / "screenshots"
    if screenshots_dir.exists():
        return screenshots_dir
    if is_expo_platform(platform):
        # expo 派生平台的截图可能在共享源码目录 generated_projects/expo/ 下
        shared = sample_dir / "generated_projects" / EXPO_SHARED_DIR / "screenshots"
        if shared.exists():
            return shared
    alt = sample_dir / "screenshots" / platform
    if alt.exists():
        return alt
    alt2 = sample_dir / "screenshots"
    if alt2.exists():
        return alt2
    return screenshots_dir


def score_one(workspace_dir, sample_id, platform, rules, dry_run, force, model=None):
    """对单个 (workspace, sample, platform) 进行美观度评分。

    返回字典: status in ("scored"|"skipped"|"failed"|"dry_run")
    """
    sample_dir = workspace_dir / sample_id
    result_base = {
        "workspace": workspace_dir.name,
        "sample_id": sample_id,
        "platform": platform,
        "old_score": None,
        "new_score": None,
        "reason": "",
    }

    try:
        scores = read_scores(workspace_dir, sample_id) or {}
    except Exception as e:
        return {**result_base, "status": "failed",
                "reason": "读取 scores.json 失败: {}".format(e)}

    platforms_data = scores.get("platforms", {})
    platform_data = platforms_data.get(platform, {})
    old_score = platform_data.get("aesthetics_score")
    result_base["old_score"] = old_score

    if old_score is not None and not force:
        return {**result_base, "status": "skipped",
                "reason": "已有评分，跳过（使用 --force 强制重新评分）"}

    if dry_run:
        if old_score is None:
            reason = "dry-run：将进行评分（无旧评分）"
        else:
            reason = "dry-run：将重新评分（旧分 {})".format(old_score)
        return {**result_base, "status": "dry_run", "reason": reason}

    screenshots_dir = get_screenshots_dir(workspace_dir, sample_id, platform)

    try:
        frames = select_key_frames(screenshots_dir, platform, max_count=5)
    except Exception as e:
        return {**result_base, "status": "failed",
                "reason": "选取截图失败: {}".format(e)}

    if not frames:
        return {**result_base, "status": "skipped",
                "reason": "无可用截图（目录: {}）".format(screenshots_dir)}

    app_category = get_app_category(workspace_dir, sample_id)
    trace_path = sample_dir / "aesthetics_trace_{}.json".format(platform)

    try:
        ai_result = score_aesthetics_with_ai(
            frames=frames,
            rules=rules,
            sample_dir=sample_dir,
            trace_path=trace_path,
            app_category=app_category,
            model=model,
            platform=platform,
        )
    except Exception as e:
        return {**result_base, "status": "failed",
                "reason": "AI 评分异常: {}".format(e)}

    if ai_result is None:
        return {**result_base, "status": "failed",
                "reason": "AI 评分返回 None（CLI 失败或无截图）"}

    try:
        if "platforms" not in scores:
            scores["platforms"] = {}
        if platform not in scores["platforms"]:
            scores["platforms"][platform] = {}

        scores["platforms"][platform].update({
            "aesthetics_score": ai_result.overall,
            "aesthetics_reason": ai_result.comment,
            "aesthetics_issues": ai_result.issues,
            "aesthetics_dimensions": ai_result.dimensions,
            "aesthetics_rule_version": ai_result.rule_version,
            "aesthetics_scored_frames": ai_result.scored_frames,
        })
        write_scores(workspace_dir, sample_id, scores)
    except Exception as e:
        return {**result_base, "status": "failed",
                "reason": "写入 scores.json 失败: {}".format(e)}

    result_base["new_score"] = ai_result.overall
    return {
        **result_base,
        "status": "scored",
        "reason": "评分成功: {} -> {}".format(old_score, ai_result.overall),
    }


def build_task_list(factory_dir, workspace_filter, sample_filter, platform_filter):
    workspaces = enumerate_workspaces(factory_dir, workspace_filter)
    if not workspaces:
        logger.warning("未找到有效工作区（factory: %s, filter: %s）", factory_dir, workspace_filter)
        return []
    tasks = []
    for ws in workspaces:
        samples = enumerate_samples(ws, sample_filter)
        for sid in samples:
            platforms = enumerate_platforms(ws, sid, platform_filter)
            for plat in platforms:
                tasks.append((ws, sid, plat))
    return tasks


def print_summary(stats, failures):
    logger.info("=" * 60)
    logger.info("评分完成统计：")
    logger.info("  扫描工作区数：  %d", stats["workspaces"])
    logger.info("  扫描样本数：    %d", stats["samples"])
    logger.info("  处理任务总数：  %d", stats["total"])
    logger.info("  已评分：        %d", stats["scored"])
    logger.info("  已跳过：        %d", stats["skipped"])
    logger.info("  dry-run：       %d", stats["dry_run"])
    logger.info("  失败：          %d", stats["failed"])

    if stats["scored"] > 0:
        logger.info("")
        logger.info("评分变化记录（仅已评分项）：")
        for r in stats["score_changes"]:
            old = "{:.1f}".format(r["old_score"]) if r["old_score"] is not None else "无"
            new = "{:.1f}".format(r["new_score"]) if r["new_score"] is not None else "?"
            logger.info(
                "  %s / %s / %s: %s -> %s",
                r["workspace"], r["sample_id"], r["platform"], old, new,
            )

    if failures:
        logger.warning("")
        logger.warning("失败列表（共 %d 项）：", len(failures))
        for f in failures:
            logger.warning(
                "  [FAIL] %s / %s / %s: %s",
                f["workspace"], f["sample_id"], f["platform"], f["reason"],
            )
    logger.info("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="对所有工作区的所有样本重新进行美观度评分",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--workspace",
        metavar="NAME",
        default=None,
        help="只处理指定工作区名称",
    )
    parser.add_argument(
        "--sample",
        metavar="SAMPLE_ID",
        default=None,
        help="只处理指定样本 ID",
    )
    parser.add_argument(
        "--platform",
        metavar="PLATFORM",
        default=None,
        help="只处理指定平台（如 android/ios/miniprogram/expo_web/expo_ios/expo_android）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只统计，不实际评分",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="强制重新评分（即使已有评分）",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        metavar="N",
        help="并发任务数（默认 1）",
    )
    parser.add_argument(
        "--factory-dir",
        metavar="DIR",
        default=None,
        help="手动指定 eval_app_factory 目录（覆盖环境变量）",
    )
    parser.add_argument(
        "--model",
        metavar="MODEL",
        default=None,
        help="指定美观度评分使用的模型（如 qwen3.6-plus），默认读取 evalapp.yaml 配置",
    )
    args = parser.parse_args()

    if args.factory_dir:
        factory_dir = Path(args.factory_dir).expanduser().resolve()
    else:
        factory_dir = get_eval_app_factory()

    logger.info("eval_app_factory: %s", factory_dir)
    logger.info(
        "参数: workspace=%s sample=%s platform=%s dry_run=%s force=%s concurrency=%d",
        args.workspace, args.sample, args.platform,
        args.dry_run, args.force, args.concurrency,
    )

    if not AESTHETICS_RULES_PATH.exists():
        logger.error("美观度规则文件不存在: %s", AESTHETICS_RULES_PATH)
        sys.exit(1)

    try:
        rules = load_aesthetics_rules(AESTHETICS_RULES_PATH)
        logger.info("已加载美观度规则 (version=%s)", rules.get("version", "unknown"))
    except Exception as e:
        logger.error("加载美观度规则失败: %s", e)
        sys.exit(1)

    # 确定美观度评分模型：CLI参数优先，否则读 evalapp.yaml
    aesthetics_model = args.model
    if not aesthetics_model:
        try:
            from evalapp.config import get_config
            cfg = get_config()
            aesthetics_model = cfg.claude.aesthetics_model or None
        except Exception:
            aesthetics_model = None

    tasks = build_task_list(factory_dir, args.workspace, args.sample, args.platform)
    if not tasks:
        logger.warning("没有找到任何待处理任务，退出")
        sys.exit(0)

    unique_workspaces = len({ws.name for ws, _, _ in tasks})
    unique_samples = len({(ws.name, sid) for ws, sid, _ in tasks})
    logger.info(
        "任务统计: %d 个工作区, %d 个样本, %d 个评分任务",
        unique_workspaces, unique_samples, len(tasks),
    )

    stats = {
        "workspaces": unique_workspaces,
        "samples": unique_samples,
        "total": len(tasks),
        "scored": 0,
        "skipped": 0,
        "dry_run": 0,
        "failed": 0,
        "score_changes": [],
    }
    failures = []

    def run_task(task_args):
        ws_dir, sid, plat = task_args
        label = "{}/{}/{}".format(ws_dir.name, sid, plat)
        logger.info("[START] %s", label)
        return score_one(
            workspace_dir=ws_dir,
            sample_id=sid,
            platform=plat,
            rules=rules,
            dry_run=args.dry_run,
            force=args.force,
            model=aesthetics_model,
        )

    if args.concurrency <= 1:
        results = [run_task(t) for t in tasks]
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
            results = list(executor.map(run_task, tasks))

    for r in results:
        status = r["status"]
        label = "{}/{}/{}".format(r["workspace"], r["sample_id"], r["platform"])

        if status == "scored":
            stats["scored"] += 1
            stats["score_changes"].append(r)
            logger.info("[OK]   %s: %s", label, r["reason"])
        elif status == "skipped":
            stats["skipped"] += 1
            logger.debug("[SKIP] %s: %s", label, r["reason"])
        elif status == "dry_run":
            stats["dry_run"] += 1
            logger.info("[DRY]  %s: %s", label, r["reason"])
        elif status == "failed":
            stats["failed"] += 1
            failures.append(r)
            logger.error("[FAIL] %s: %s", label, r["reason"])

    print_summary(stats, failures)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
