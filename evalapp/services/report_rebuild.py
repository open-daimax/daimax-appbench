"""报告数据重建工具 - 从各样本 scores.json 原始数据聚合生成等价报告数据。

当 report/scores_summary.json 和 report_data.json 均不存在时，
扫描工作区下各样本目录的 scores.json，动态聚合生成与 scores_summary.json
兼容的报告数据结构，作为报告生成的 fallback 路径。
"""

import hashlib
import json
import logging
from pathlib import Path

from ..utils.currency import extract_cost_usd

logger = logging.getLogger(__name__)

# 非样本目录黑名单 - 扫描时跳过这些目录名
_NON_SAMPLE_DIRS = frozenset({
    "runs",
    "report",
    "archive",
    "analyzer",
    "e2e_reports",
    "stability_logs",
    "__pycache__",
    ".venv",
    "node_modules",
    "dist",
    ".DS_Store",
})


def _get_excluded_workspace_dirs() -> frozenset[str]:
    """Return the combined set of non-sample dirs (static + config-driven)."""
    try:
        from ..config import get_config
        extra = get_config().excluded_workspace_dirs or []
    except Exception:
        extra = []
    if not extra:
        return _NON_SAMPLE_DIRS
    return _NON_SAMPLE_DIRS | frozenset(extra)


def rebuild_report_data_from_samples(workspace: Path) -> dict | None:
    """从各样本的 scores.json 重建报告数据（fallback 路径）。

    当 report/scores_summary.json 和 report_data.json 均不存在时，
    扫描工作区下各样本目录的 scores.json，动态聚合生成等价的报告数据。

    Args:
        workspace: 工作区根目录路径

    Returns:
        聚合后的 report_data dict，结构与 scores_summary.json 兼容；
        如果没有找到任何有效的 scores.json，返回 None。
    """
    workspace = Path(workspace)

    # === 1. 扫描样本目录，收集有效 scores.json ===
    sample_dirs = _scan_sample_dirs(workspace)
    if not sample_dirs:
        logger.warning("No valid sample directories found in workspace: %s", workspace)
        return None

    logger.info("Found %d sample directories with scores.json in %s", len(sample_dirs), workspace)

    # === 2. 读取工作区元数据 ===
    meta_info = _read_workspace_meta(workspace)

    # === 3. 尝试从 execution_manifest.json 获取 overall_pass_rate ===
    manifest_info = _read_manifest_summary(workspace)

    # === 4. 逐样本读取 scores.json 并聚合 ===
    sample_results_data: list[dict] = []
    # 按平台收集各维度的分数列表，用于计算均值
    platform_scores: dict[str, dict[str, list[float]]] = {}
    # 全局各维度分数列表
    global_scores: dict[str, list[float]] = {
        "success_rate": [],
        "quality": [],
        "experience": [],
        "stability": [],
        "aesthetics": [],
        "functionality": [],
        "backend_completeness": [],
        "duration_ms": [],
        "token_total": [],
        "cost_usd": [],
    }
    # 计入聚合的样本数（去重，用于 top_level_summary）
    unique_sample_ids: set[str] = set()

    for sample_id, sample_dir in sorted(sample_dirs.items()):
        scores_path = sample_dir / "scores.json"
        try:
            scores_raw = json.loads(scores_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to read scores.json for sample '%s': %s", sample_id, exc)
            continue

        if not isinstance(scores_raw, dict) or "platforms" not in scores_raw:
            logger.warning("Invalid scores.json format for sample '%s': missing 'platforms' key", sample_id)
            continue

        # 识别该样本覆盖的平台
        platforms_list = list(scores_raw.get("platforms", {}).keys())
        if not platforms_list:
            logger.warning("Sample '%s' has no platform entries in scores.json", sample_id)
            continue

        unique_sample_ids.add(sample_id)

        # 展开为扁平化的样本-平台条目（与前端期望的 sample_results 结构对齐）
        for plat_name, plat_scores in scores_raw.get("platforms", {}).items():
            if not isinstance(plat_scores, dict):
                continue

            # 构建扁平条目：sample_id + platform + 所有分数字段直接平铺
            flat_entry = {"sample_id": sample_id, "platform": plat_name}
            flat_entry.update(plat_scores)
            sample_results_data.append(flat_entry)

            # 收集各平台×维度的分数
            if plat_name not in platform_scores:
                platform_scores[plat_name] = {
                    "success_rate": [],
                    "quality": [],
                    "experience": [],
                    "stability": [],
                    "aesthetics": [],
                    "functionality": [],
                    "backend_completeness": [],
                    "duration_ms": [],
                    "token_total": [],
                    "cost_usd": [],
                }

            _append_score(platform_scores[plat_name]["success_rate"], plat_scores, "success_rate_score")
            _append_score(platform_scores[plat_name]["quality"], plat_scores, "quality_score")
            _append_score(platform_scores[plat_name]["experience"], plat_scores, "experience_score")
            _append_score(platform_scores[plat_name]["stability"], plat_scores, "stability_score")
            _append_score(platform_scores[plat_name]["aesthetics"], plat_scores, "aesthetics_score")
            _append_score(platform_scores[plat_name]["functionality"], plat_scores, "functionality_score")
            _append_score(platform_scores[plat_name]["backend_completeness"], plat_scores, "backend_completeness")
            _append_score(platform_scores[plat_name]["duration_ms"], plat_scores, "duration_ms")
            _append_score(platform_scores[plat_name]["token_total"], plat_scores, "token_total")
            _append_cost_usd(platform_scores[plat_name]["cost_usd"], plat_scores)

            # 同时收集到全局
            _append_score(global_scores["success_rate"], plat_scores, "success_rate_score")
            _append_score(global_scores["quality"], plat_scores, "quality_score")
            _append_score(global_scores["experience"], plat_scores, "experience_score")
            _append_score(global_scores["stability"], plat_scores, "stability_score")
            _append_score(global_scores["aesthetics"], plat_scores, "aesthetics_score")
            _append_score(global_scores["functionality"], plat_scores, "functionality_score")
            _append_score(global_scores["backend_completeness"], plat_scores, "backend_completeness")
            _append_score(global_scores["duration_ms"], plat_scores, "duration_ms")
            _append_score(global_scores["token_total"], plat_scores, "token_total")
            _append_cost_usd(global_scores["cost_usd"], plat_scores)

    if not sample_results_data:
        logger.warning("No valid scores.json data could be read from workspace: %s", workspace)
        return None

    logger.info("Successfully aggregated %d sample-platform entries from %d samples",
                len(sample_results_data), len(unique_sample_ids))

    # === 4b. 从 sample_report.json / evaluation.json 补充 E2E、Token、耗时等明细数据 ===
    # scores.json 不包含 e2e_test_cases / token_total / duration_ms 等，需从 sample_report.json 或 evaluation.json 读取
    platform_e2e: dict[str, dict[str, int]] = {}  # {plat: {e2e_pass, e2e_count}}
    for sample_id, sample_dir in sorted(sample_dirs.items()):
        # 优先从 sample_report.json 读取（已 consolidate 的工作区）
        e2e_found = False
        report_path = sample_dir / "sample_report.json"
        if report_path.exists():
            try:
                report_raw = json.loads(report_path.read_text(encoding="utf-8"))
                report_platforms = report_raw.get("platforms", {})
                if isinstance(report_platforms, dict):
                    for plat_name, plat_data in report_platforms.items():
                        if not isinstance(plat_data, dict):
                            continue
                        e2e_cases = plat_data.get("e2e_test_cases", [])
                        if e2e_cases and isinstance(e2e_cases, list):
                            e2e_found = True
                            passed = sum(
                                1 for c in e2e_cases
                                if isinstance(c, dict) and _is_tc_passed(c)
                            )
                            total = len(e2e_cases)
                            if plat_name not in platform_e2e:
                                platform_e2e[plat_name] = {"e2e_pass": 0, "e2e_count": 0}
                            platform_e2e[plat_name]["e2e_pass"] += passed
                            platform_e2e[plat_name]["e2e_count"] += total
                        # functionality_score (if available from sample_report but not scores.json)
                        func_score = plat_data.get("functionality_score")
                        if func_score is not None and isinstance(func_score, (int, float)):
                            if plat_name in platform_scores:
                                platform_scores[plat_name]["functionality"].append(float(func_score))
                                global_scores["functionality"].append(float(func_score))

                # 读取 platform_tokens 和 platform_durations（存储在 sample_report 顶层）
                plat_tokens = report_raw.get("platform_tokens", {})
                plat_durations = report_raw.get("platform_durations", {})
                for plat_name in set(list(plat_tokens.keys()) + list(plat_durations.keys())):
                    if plat_name not in platform_scores:
                        continue
                    # token_total
                    tok_info = plat_tokens.get(plat_name, {})
                    if isinstance(tok_info, dict):
                        tok_val = tok_info.get("token_total")
                        if tok_val is not None and isinstance(tok_val, (int, float)):
                            platform_scores[plat_name]["token_total"].append(float(tok_val))
                            global_scores["token_total"].append(float(tok_val))
                        cost_val = extract_cost_usd(tok_info)
                        if cost_val is not None:
                            platform_scores[plat_name]["cost_usd"].append(cost_val)
                            global_scores["cost_usd"].append(cost_val)
                    # duration_ms
                    dur_val = plat_durations.get(plat_name)
                    if dur_val is not None and isinstance(dur_val, (int, float)):
                        platform_scores[plat_name]["duration_ms"].append(float(dur_val))
                        global_scores["duration_ms"].append(float(dur_val))
            except (json.JSONDecodeError, OSError):
                pass

        # Fallback: 旧工作区的 e2e 数据可能在 evaluation.json 而非 sample_report.json
        if not e2e_found:
            eval_path = sample_dir / "evaluation.json"
            if eval_path.exists():
                try:
                    eval_raw = json.loads(eval_path.read_text(encoding="utf-8"))
                    eval_platforms = eval_raw.get("platforms", {})
                    if isinstance(eval_platforms, dict):
                        for plat_name, plat_eval in eval_platforms.items():
                            if not isinstance(plat_eval, dict):
                                continue
                            test_results = plat_eval.get("test_results", [])
                            if test_results and isinstance(test_results, list):
                                passed = sum(
                                    1 for c in test_results
                                    if isinstance(c, dict) and _is_tc_passed(c)
                                )
                                total = len(test_results)
                                if plat_name not in platform_e2e:
                                    platform_e2e[plat_name] = {"e2e_pass": 0, "e2e_count": 0}
                                platform_e2e[plat_name]["e2e_pass"] += passed
                                platform_e2e[plat_name]["e2e_count"] += total
                except (json.JSONDecodeError, OSError):
                    pass

    # === 5. 计算全局和各平台的均值 ===
    sample_count = len(unique_sample_ids)
    global_means = _compute_means(global_scores)
    per_platform_means = {}
    for plat_name, plat_score_lists in platform_scores.items():
        per_platform_means[plat_name] = _compute_means(plat_score_lists)
        per_platform_means[plat_name]["sample_count"] = len(plat_score_lists["success_rate"])
        # 注入 E2E 统计数据
        if plat_name in platform_e2e:
            e2e_data = platform_e2e[plat_name]
            per_platform_means[plat_name]["e2e_pass"] = e2e_data["e2e_pass"]
            per_platform_means[plat_name]["e2e_count"] = e2e_data["e2e_count"]
            if e2e_data["e2e_count"] > 0:
                per_platform_means[plat_name]["e2e_pass_rate"] = round(
                    e2e_data["e2e_pass"] / e2e_data["e2e_count"] * 100, 1
                )
                # 当 functionality_score 缺失时，用 E2E 通过率作为用例完整性
                if not per_platform_means[plat_name].get("mean_usecase_completeness"):
                    per_platform_means[plat_name]["mean_usecase_completeness"] = (
                        per_platform_means[plat_name]["e2e_pass_rate"]
                    )

    # === 6. 确定主平台 ===
    platforms_from_meta = meta_info.get("platforms", [])
    primary_platform = platforms_from_meta[0] if platforms_from_meta else (
        list(platform_scores.keys())[0] if platform_scores else "unknown"
    )

    # === 7. 构建输出结构 ===
    # 生成一个稳定的 run_id（基于工作区路径），确保前端 reportResetKey 在数据加载后必然变化
    run_id = f"rebuilt_{hashlib.md5(str(workspace).encode()).hexdigest()[:12]}"

    result = {
        "meta": {
            "run_id": run_id,
            "eval_version": meta_info.get("eval_version", ""),
            "dataset_version": meta_info.get("dataset", ""),
            "generator": meta_info.get("generator", ""),
            "platform": primary_platform,
            "workspace_name": meta_info.get("workspace_name", str(workspace)),
            "aggregated_from_raw": True,
        },
        "summary": {
            "total_prompts": sample_count,
            "overall_pass_rate": manifest_info.get("overall_pass_rate"),
        },
        "top_level_summary": {
            "sample_count": sample_count,
            "mean_success_rate": global_means.get("mean_success_rate", 0),
            "mean_quality": global_means.get("mean_quality", 0),
            "mean_experience": global_means.get("mean_experience", 0),
            "mean_stability_score": global_means.get("mean_stability_score", 0),
            "mean_aesthetics_score": global_means.get("mean_aesthetics_score"),
            "mean_usecase_completeness": global_means.get("mean_usecase_completeness", 0),
            "mean_backend_completeness": global_means.get("mean_backend_completeness", 0),
            "mean_initial_generation_rate": global_means.get("mean_initial_generation_rate", 0),
            "mean_duration_ms": global_means.get("mean_duration_ms", 0),
            "mean_token_total": global_means.get("mean_token_total", 0),
            "mean_cost_usd": global_means.get("mean_cost_usd"),
            "e2e_pass_rate": global_means.get("e2e_pass_rate", 0),
            "per_platform": per_platform_means,
        },
        "sample_results": sample_results_data,
    }

    logger.info(
        "Rebuilt report data: %d samples, global success_rate=%.1f, quality=%.1f, "
        "experience=%.1f, stability=%.1f, aesthetics=%s",
        sample_count,
        global_means.get("mean_success_rate", 0),
        global_means.get("mean_quality", 0),
        global_means.get("mean_experience", 0),
        global_means.get("mean_stability", 0),
        global_means.get("mean_aesthetics", "N/A"),
    )

    return result


# ====================== 内部辅助函数 ======================


def _is_tc_passed(tc: dict) -> bool:
    """判断测试用例是否通过，尊重 manual_override 标记。

    如果存在 manual_override 字段，使用 new_status 判断；
    否则回退到原始 status/passed 字段。
    """
    override = tc.get("manual_override")
    if override and isinstance(override, dict):
        return override.get("new_status") == "PASS"
    # 兼容旧格式：优先 status 字段，回退到 passed 布尔值
    status = tc.get("status")
    if status is not None:
        return status == "PASS"
    return bool(tc.get("passed", False))


def _scan_sample_dirs(workspace: Path) -> dict[str, Path]:
    """扫描工作区子目录，识别包含 scores.json 的有效样本目录。

    排除黑名单目录（runs、report 等）和隐藏目录。

    Returns:
        {sample_id: sample_dir_path} 字典
    """
    sample_dirs: dict[str, Path] = {}
    excluded = _get_excluded_workspace_dirs()
    for entry in workspace.iterdir():
        if not entry.is_dir():
            continue
        name = entry.name
        # 跳过隐藏目录和黑名单目录
        if name.startswith(".") or name in excluded:
            continue
        # 识别包含 scores.json 的目录作为有效样本
        scores_file = entry / "scores.json"
        if scores_file.exists():
            sample_dirs[name] = entry
    return sample_dirs


def _read_workspace_meta(workspace: Path) -> dict:
    """读取工作区的 meta.json 元数据。

    如果 meta.json 不存在或读取失败，返回合理默认值。

    Returns:
        包含 workspace_name、generator、platforms、dataset、created_at、eval_version 的 dict
    """
    meta_path = workspace / "meta.json"
    if not meta_path.exists():
        logger.info("meta.json not found in workspace, using defaults")
        return {
            "workspace_name": workspace.name,
            "generator": "",
            "platforms": [],
            "dataset": "",
            "created_at": "",
            "eval_version": "",
        }

    try:
        meta_raw = json.loads(meta_path.read_text(encoding="utf-8"))
        if not isinstance(meta_raw, dict):
            logger.warning("meta.json is not a dict, using defaults")
            return {
                "workspace_name": workspace.name,
                "generator": "",
                "platforms": [],
                "dataset": "",
                "created_at": "",
                "eval_version": "",
            }
        return {
            "workspace_name": meta_raw.get("workspace_name", workspace.name),
            "generator": meta_raw.get("generator", ""),
            "platforms": meta_raw.get("platforms", []),
            "dataset": meta_raw.get("dataset", ""),
            "created_at": meta_raw.get("created_at", ""),
            "eval_version": meta_raw.get("eval_version", ""),
        }
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to read meta.json: %s, using defaults", exc)
        return {
            "workspace_name": workspace.name,
            "generator": "",
            "platforms": [],
            "dataset": "",
            "created_at": "",
            "eval_version": "",
        }


def _read_manifest_summary(workspace: Path) -> dict:
    """从 execution_manifest.json 读取 overall_pass_rate。

    Returns:
        {"overall_pass_rate": float | None} 如果能从 manifest 计算出则提供值，否则 None
    """
    manifest_path = workspace / "execution_manifest.json"
    if not manifest_path.exists():
        return {"overall_pass_rate": None}

    try:
        manifest_raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to read execution_manifest.json: %s", exc)
        return {"overall_pass_rate": None}

    if not isinstance(manifest_raw, dict) or "items" not in manifest_raw:
        return {"overall_pass_rate": None}

    # 从 manifest items 中计算平均 pass_rate
    pass_rates: list[float] = []
    for item in manifest_raw.get("items", []):
        evaluate_phase = item.get("phases", {}).get("evaluate", {})
        if isinstance(evaluate_phase, dict) and "pass_rate" in evaluate_phase:
            pr = evaluate_phase["pass_rate"]
            if isinstance(pr, (int, float)):
                pass_rates.append(float(pr))

    if pass_rates:
        overall_rate = round(sum(pass_rates) / len(pass_rates), 2)
        return {"overall_pass_rate": overall_rate}

    return {"overall_pass_rate": None}


def _append_score(target_list: list[float], plat_scores: dict, key: str) -> None:
    """从 plat_scores dict 中提取指定 key 的分数值，追加到 target_list。

    仅追加有效数值（跳过 None 和非数值）。
    """
    value = plat_scores.get(key)
    if value is not None and isinstance(value, (int, float)):
        target_list.append(float(value))


def _append_cost_usd(target_list: list[float], plat_scores: dict) -> None:
    """提取美元成本追加到 target_list（仅有 cost_cny 人民币时按汇率折算）。"""
    value = extract_cost_usd(plat_scores)
    if value is not None:
        target_list.append(value)


def _compute_means(score_lists: dict[str, list[float]]) -> dict:
    """从各维度的分数列表计算均值。

    Args:
        score_lists: {"success_rate": [100, 80, ...], "quality": [...], ...}

    Returns:
        {"mean_success_rate": X, "mean_quality": X, ...}
        aesthetics 维度如果没有有效值，则 mean_aesthetics 为 None
    """
    result: dict = {}
    dimension_map = {
        "success_rate": "mean_success_rate",
        "quality": "mean_quality",
        "experience": "mean_experience",
        "stability": "mean_stability_score",
        "aesthetics": "mean_aesthetics_score",
        "functionality": "mean_usecase_completeness",
        "backend_completeness": "mean_backend_completeness",
        "duration_ms": "mean_duration_ms",
        "token_total": "mean_token_total",
        "cost_usd": "mean_cost_usd",
    }

    # 允许为 None 的维度（无数据时不输出 0）
    nullable_dims = {"aesthetics", "cost_usd"}

    for dim_key, mean_key in dimension_map.items():
        values = score_lists.get(dim_key, [])
        if values:
            precision = 1
            if dim_key == "token_total":
                precision = 0
            elif dim_key == "cost_usd":
                precision = 6
            result[mean_key] = round(sum(values) / len(values), precision)
        elif dim_key in nullable_dims:
            result[mean_key] = None
        else:
            result[mean_key] = 0

    # 派生指标：初次生成率 = 成功率
    result["mean_initial_generation_rate"] = result.get("mean_success_rate", 0)

    # 派生指标：e2e_pass_rate（需要从外部计算，这里默认 0）
    result.setdefault("e2e_pass_rate", 0)

    return result