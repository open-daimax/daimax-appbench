"""报告数据回填与迁移辅助模块。

从 commands/reporting.py 抽取的纯数据处理函数：
- manifest 过滤辅助
- sample_report.json 缓存与回填
- e2e_report 路径迁移
- 平台/分类/耗时回填与重计算

这些函数都是纯函数（或仅依赖文件系统读写），不包含 CLI 逻辑。
"""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..utils.json_io import read_json as _read_json
from ..utils.logging import get_logger

logger = get_logger(__name__)


# ====================== Manifest 过滤辅助 ======================

def load_manifest_exclusions(workspace_dir: Path):
    """从 execution_manifest.json 读取应被排除的样本×平台集合。

    Returns:
        二元组（None 表示 manifest 不存在或加载失败，按原有全量逻辑走）:
            - excluded_pairs: {(sample_id, platform): exclude_reason}
            - sample_overall: {sample_id: overall_status}
        出错或 manifest 不存在 → 返回 None，保证向后兼容。
    """
    try:
        from ..evaluation.execution_manifest import (
            ExecutionManifest, PHASE_COMPLETED, PHASE_FAILED,
            PHASE_SKIPPED,
        )
    except Exception:
        return None

    try:
        manifest = ExecutionManifest.load(workspace_dir)
    except Exception as exc:
        logger.warning("Failed to load execution manifest at %s: %s", workspace_dir, exc)
        return None
    if manifest is None:
        return None

    excluded: dict[tuple[str, str], str] = {}
    sample_overall: dict[str, str] = {}
    has_any_terminal_marker = False
    try:
        items = manifest.to_dict().get("items", [])
    except Exception:
        items = []
    for it in items:
        sid = str(it.get("sample_id", "") or "")
        plat = str(it.get("platform", "") or "")
        overall = str(it.get("overall_status", "") or "")
        if not sid or not plat:
            continue
        if overall in (PHASE_COMPLETED, PHASE_FAILED, PHASE_SKIPPED):
            has_any_terminal_marker = True
        prev = sample_overall.get(sid)
        if prev != PHASE_COMPLETED:
            sample_overall[sid] = overall
        if overall == PHASE_FAILED:
            excluded[(sid, plat)] = "evaluation_failed"
        elif overall == PHASE_SKIPPED:
            excluded[(sid, plat)] = "skipped"

    if not has_any_terminal_marker:
        return {}, sample_overall
    return excluded, sample_overall


def build_excluded_summary(excluded_pairs, sample_overall) -> list[dict]:
    """将 manifest 中被排除的样本×平台转换为报告中的标记项。"""
    rows: list[dict] = []
    for (sid, plat), reason in sorted(excluded_pairs.items()):
        rows.append({
            "sample_id": sid,
            "platform": plat,
            "excluded": True,
            "exclude_reason": reason,
            "sample_overall_status": sample_overall.get(sid, ""),
        })
    return rows


def filter_run_by_manifest(run, excluded_pairs):
    """过滤 EvalRun.prompt_results，只保留 manifest 未标记为 failed/skipped 的条目。"""
    if not excluded_pairs:
        return len(run.prompt_results), 0
    kept = []
    dropped = 0
    for pr in run.prompt_results:
        sid = getattr(pr, "item_id", None) or getattr(pr, "sample_id", "") or getattr(pr, "prompt_id", "")
        plat = getattr(pr, "platform", "") or ""
        if (str(sid), str(plat)) in excluded_pairs:
            dropped += 1
            continue
        kept.append(pr)
    run.prompt_results = kept
    return len(kept), dropped


def filter_report_data_by_manifest(report_data_raw: dict, excluded_pairs) -> int:
    """原地过滤 report_data_raw['sample_results']，返回被丢弃的条数。"""
    if not excluded_pairs:
        return 0
    sr_list = report_data_raw.get("sample_results", [])
    if not isinstance(sr_list, list):
        return 0
    kept = []
    dropped = 0
    for sr in sr_list:
        sid = str(sr.get("sample_id", "") or "")
        plat = str(sr.get("platform", "") or "")
        if (sid, plat) in excluded_pairs:
            dropped += 1
            continue
        kept.append(sr)
    report_data_raw["sample_results"] = kept
    return dropped


# ====================== sample_report.json 缓存与回填 ======================

def load_sample_report_cache(workspace: Path) -> dict[str, dict]:
    """统一加载工作区下所有 sample_report.json 到内存缓存。"""
    cache: dict[str, dict] = {}
    report_paths: list[tuple[str, Path]] = []
    for sample_dir in workspace.iterdir():
        if not sample_dir.is_dir():
            continue
        report_path = sample_dir / "sample_report.json"
        if report_path.exists():
            report_paths.append((sample_dir.name, report_path))

    if not report_paths:
        return cache

    def _load_one(item: tuple[str, Path]):
        name, path = item
        try:
            return name, _read_json(path)
        except Exception:
            return name, None

    max_workers = min(8, len(report_paths))
    if max_workers <= 1:
        for item in report_paths:
            name, data = _load_one(item)
            if data is not None:
                cache[name] = data
        return cache

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        for name, data in ex.map(_load_one, report_paths):
            if data is not None:
                cache[name] = data
    return cache


def backfill_category_from_dataset(report_data_raw: dict) -> None:
    """从 dataset 目录的 sample.yaml 获取正确的 app_type，回补 top_category。"""
    import yaml
    sample_results = report_data_raw.get("sample_results", [])
    if not sample_results:
        return

    dataset_base = Path(__file__).parent.parent.parent / "dataset"
    category_map: dict[str, str] = {}
    if dataset_base.exists():
        for category_dir in dataset_base.iterdir():
            if not category_dir.is_dir():
                continue
            for sample_dir in category_dir.iterdir():
                if not sample_dir.is_dir():
                    continue
                sample_yaml = sample_dir / "sample.yaml"
                if sample_yaml.exists():
                    try:
                        with open(sample_yaml, encoding="utf-8") as f:
                            data = yaml.safe_load(f)
                        if data and data.get("sample_id") and data.get("app_type"):
                            category_map[data["sample_id"]] = data["app_type"]
                    except (OSError, yaml.YAMLError) as e:
                        logger.debug("读取 sample.yaml 失败 (%s): %s", sample_yaml, e)

    if not category_map:
        return

    for item in sample_results:
        sample_id = item.get("sample_id", "")
        if sample_id in category_map:
            item["top_category"] = category_map[sample_id]


def migrate_e2e_report_paths(report_data_raw: dict, workspace: Path) -> None:
    """将 e2e_test_cases 中绝对本地路径的 report_path 转换为导出后的相对路径。"""
    from evalapp.evaluation.results.reporting.e2e_paths import migrate_e2e_report_paths as _migrate

    _migrate(report_data_raw, workspace)


def backfill_platform_token(report_data_raw: dict) -> None:
    """从 sample_results 反向计算各平台平均 Token，回填到 per_platform。"""
    sample_results = report_data_raw.get("sample_results", [])
    per_platform = (
        report_data_raw.get("top_level_summary") or {}
    ).get("per_platform")
    if not sample_results or not per_platform:
        return

    platform_tokens: dict[str, dict[str, list[int]]] = {}
    for sr in sample_results:
        plat = sr.get("platform", "")
        token_input = sr.get("token_input", 0) or 0
        token_output = sr.get("token_output", 0) or 0
        token_total = sr.get("token_total", 0) or 0
        if plat and token_total > 0:
            if plat not in platform_tokens:
                platform_tokens[plat] = {"input": [], "output": [], "total": []}
            platform_tokens[plat]["input"].append(token_input)
            platform_tokens[plat]["output"].append(token_output)
            platform_tokens[plat]["total"].append(token_total)

    for plat, tokens in platform_tokens.items():
        if plat in per_platform:
            per_platform[plat]["mean_token_input"] = round(sum(tokens["input"]) / len(tokens["input"])) if tokens["input"] else 0
            per_platform[plat]["mean_token_output"] = round(sum(tokens["output"]) / len(tokens["output"])) if tokens["output"] else 0
            per_platform[plat]["mean_token_total"] = round(sum(tokens["total"]) / len(tokens["total"])) if tokens["total"] else 0


def backfill_platform_e2e(report_data_raw: dict) -> None:
    """从 sample_results 的 e2e_test_cases 统计E2E通过/总次数，回填到 sample_results 和 per_platform。"""
    sample_results = report_data_raw.get("sample_results", [])
    per_platform = (
        report_data_raw.get("top_level_summary") or {}
    ).get("per_platform")
    if not sample_results:
        return

    for sr in sample_results:
        e2e_cases = sr.get("e2e_test_cases", [])
        if e2e_cases:
            pass_count = sum(
                1 for case in e2e_cases
                if case.get("status") == "PASS" or case.get("passed")
            )
            total_count = len(e2e_cases)
            sr["e2e_pass_count"] = pass_count
            sr["e2e_total_count"] = total_count

    if per_platform:
        platform_e2e: dict[str, dict] = {}
        for sr in sample_results:
            plat = sr.get("platform", "")
            pass_count = sr.get("e2e_pass_count", 0) or 0
            total_count = sr.get("e2e_total_count", 0) or 0
            if plat:
                if plat not in platform_e2e:
                    platform_e2e[plat] = {"e2e_pass": 0, "e2e_count": 0}
                platform_e2e[plat]["e2e_pass"] += pass_count
                platform_e2e[plat]["e2e_count"] += total_count

        for plat, e2e_data in platform_e2e.items():
            if plat in per_platform:
                per_platform[plat]["e2e_pass"] = e2e_data["e2e_pass"]
                per_platform[plat]["e2e_count"] = e2e_data["e2e_count"]


def backfill_stability_detail_from_evaluation(report_data_raw: dict, workspace: Path) -> None:
    """从 evaluation.json 补充 stability_detail（含白屏数据）到 sample_results。"""
    sample_results = report_data_raw.get("sample_results", [])
    if not sample_results:
        return

    for sr in sample_results:
        if sr.get("stability_detail"):
            continue
        sample_id = sr.get("sample_id", "")
        platform = sr.get("platform", "")
        eval_path = workspace / sample_id / "evaluation.json"

        if eval_path.exists():
            try:
                eval_data = _read_json(eval_path)
            except Exception:
                eval_data = None
            if eval_data is not None:
                eval_platform = eval_data.get("platforms", {}).get(platform, {})
                stab = eval_platform.get("stability_metrics", {})
                if stab:
                    sr["stability_detail"] = {
                        "crash_events": stab.get("crash_events", []),
                        "anr_events": stab.get("anr_events", []),
                        "crash_rate": stab.get("crash_rate", 0.0),
                        "anr_rate": stab.get("anr_rate", 0.0),
                        "white_screen_count": stab.get("white_screen_count", 0),
                        "white_screen_evidence": stab.get("white_screen_evidence", []),
                    }
            continue

        sample_stab_dir = workspace / sample_id / "stability_logs"
        if sample_stab_dir.is_dir():
            for gen_dir in sample_stab_dir.iterdir():
                if not gen_dir.is_dir():
                    continue
                crash_file = gen_dir / "crash_anr_events.json"
                if crash_file.exists():
                    try:
                        stab_data = _read_json(crash_file)
                    except Exception:
                        stab_data = None
                    if stab_data is not None:
                        if stab_data.get("platform") == platform or not stab_data.get("platform"):
                            sr["stability_detail"] = {
                                "crash_events": stab_data.get("crash_events", []),
                                "anr_events": stab_data.get("anr_events", []),
                                "crash_rate": stab_data.get("crash_rate", 0.0),
                                "anr_rate": stab_data.get("anr_rate", 0.0),
                                "white_screen_count": stab_data.get("white_screen_count", 0),
                                "white_screen_evidence": stab_data.get("white_screen_evidence", []),
                            }
                            break
            if sr.get("stability_detail"):
                continue

        for stability_base in [
            workspace / "report" / "stability",
            workspace / "stability_logs",
        ]:
            if not stability_base.is_dir():
                continue
            for sub in stability_base.iterdir():
                if not sub.is_dir():
                    continue
                crash_file = sub / sample_id / "crash_anr_events.json"
                if not crash_file.exists():
                    crash_file = stability_base / sample_id / "crash_anr_events.json"
                if crash_file.exists():
                    try:
                        stab_data = _read_json(crash_file)
                    except Exception:
                        stab_data = None
                    if stab_data is not None:
                        if stab_data.get("platform") == platform or not stab_data.get("platform"):
                            sr["stability_detail"] = {
                                "crash_events": stab_data.get("crash_events", []),
                                "anr_events": stab_data.get("anr_events", []),
                                "crash_rate": stab_data.get("crash_rate", 0.0),
                                "anr_rate": stab_data.get("anr_rate", 0.0),
                                "white_screen_count": stab_data.get("white_screen_count", 0),
                                "white_screen_evidence": stab_data.get("white_screen_evidence", []),
                            }
                            break
            if sr.get("stability_detail"):
                break


def backfill_package_size_from_sample_reports(
    report_data_raw: dict, workspace: Path, *, _cache=None,
) -> None:
    """从 sample_report.json 的 platform_package_sizes 回填 package_size_bytes=0 的样本。"""
    sample_results = report_data_raw.get("sample_results", [])
    if not sample_results:
        return

    sample_report_cache = _cache if _cache is not None else load_sample_report_cache(workspace)
    if not sample_report_cache:
        return

    patched = 0
    for item in sample_results:
        if item.get("package_size_bytes", 0) != 0:
            continue
        sample_id = item.get("sample_id", "")
        platform = item.get("platform", "")
        if platform == "miniprogram":
            continue
        sr = sample_report_cache.get(sample_id)
        if not sr:
            continue
        platform_sizes = sr.get("platform_package_sizes", {})
        if isinstance(platform_sizes, dict) and platform in platform_sizes:
            size = int(platform_sizes[platform]) or 0
            if size > 0:
                item["package_size_bytes"] = size
                patched += 1

    if patched:
        logger.info("Backfilled package_size_bytes for %d samples", patched)


def backfill_duration_from_sample_reports(
    report_data_raw: dict, workspace: Path, *, _cache=None,
) -> None:
    """用 sample_report.json 中的 duration_ms 回补 report_data.json 中 duration_ms=0 的样本。"""
    sample_results = report_data_raw.get("sample_results", [])
    if not sample_results:
        return

    sample_report_cache = _cache if _cache is not None else load_sample_report_cache(workspace)
    if not sample_report_cache:
        return

    def _extract_ms(value):
        if isinstance(value, dict):
            return int(value.get("duration_ms", 0) or 0)
        if isinstance(value, (int, float)):
            return int(value)
        return 0

    patched_count = 0
    for item in sample_results:
        if item.get("duration_ms", 0) != 0:
            continue

        sample_id = item.get("sample_id", "")
        platform = item.get("platform", "")
        sr = sample_report_cache.get(sample_id)
        if not sr:
            continue

        platform_durations = sr.get("platform_durations", {})
        if platform and platform in platform_durations:
            dur_ms = _extract_ms(platform_durations[platform])
            if dur_ms > 0:
                item["duration_ms"] = dur_ms

        if item.get("duration_ms", 0) == 0:
            dur = sr.get("duration_ms") or sr.get("generation_duration", 0) or 0
            if dur:
                item["duration_ms"] = int(dur)

        if item.get("duration_ms", 0) > 0:
            patched_count += 1

    # 始终重新计算 experience_score（使用完整的三维度加权公式）
    from ..evaluation.metrics import compute_experience as _compute_experience
    for item in sample_results:
        dur = item.get("duration_ms", 0)
        if dur and dur > 0:
            pkg_size = item.get("package_size_bytes", 0)
            aes_score = item.get("aesthetics_score", None)
            exp_metrics = _compute_experience(
                duration_ms=dur,
                package_size_bytes=pkg_size,
                aesthetics_score=aes_score,
            )
            item["experience_score"] = exp_metrics.composite_score

    backfill_category_from_dataset(report_data_raw)
    recalculate_duration_statistics(report_data_raw)

    if patched_count > 0:
        logger.info(
            "Backfilled duration_ms for %d samples from sample_report.json",
            patched_count,
        )


def recalculate_duration_statistics(report_data_raw: dict) -> None:
    """根据 sample_results 中的 duration_ms 重新计算 duration_statistics 和耗时指标。"""
    sample_results = report_data_raw.get("sample_results", [])
    durations = [
        item["duration_ms"]
        for item in sample_results
        if item.get("duration_ms") is not None and item["duration_ms"] > 0
    ]

    if not durations:
        return

    import statistics as stats
    durations_sorted = sorted(durations)
    n = len(durations_sorted)
    p90_idx = min(int(n * 0.9), n - 1)
    p95_idx = min(int(n * 0.95), n - 1)

    duration_stats = {
        "total_samples": len(sample_results),
        "total": {
            "count": n,
            "mean_ms": round(stats.mean(durations), 1),
            "median_ms": round(stats.median(durations), 1),
            "p90_ms": round(durations_sorted[p90_idx], 1),
            "p95_ms": round(durations_sorted[p95_idx], 1),
            "min_ms": durations_sorted[0],
            "max_ms": durations_sorted[-1],
        },
    }

    summary = report_data_raw.get("summary", {})
    summary["duration_statistics"] = duration_stats

    tls = report_data_raw.get("top_level_summary", {})
    if tls:
        tls["mean_duration_ms"] = round(stats.mean(durations), 1)

        per_platform = tls.get("per_platform", {})
        if per_platform:
            for plat in per_platform:
                plat_durations = [
                    item["duration_ms"]
                    for item in sample_results
                    if item.get("platform") == plat
                    and item.get("duration_ms") is not None
                    and item["duration_ms"] > 0
                ]
                if plat_durations:
                    per_platform[plat]["mean_duration_ms"] = round(
                        stats.mean(plat_durations), 1
                    )


def backfill_per_platform_from_sample_results(report_data_raw: dict) -> None:
    """从 sample_results 重新计算并补齐 per_platform 中缺失的平台数据。"""
    sample_results = report_data_raw.get("sample_results", [])
    tls = report_data_raw.get("top_level_summary")
    if not sample_results or not tls:
        return

    per_platform = tls.get("per_platform", {})
    if not per_platform:
        return

    plat_samples: dict[str, list[dict]] = {}
    for sr in sample_results:
        plat = sr.get("platform", "")
        if plat:
            plat_samples.setdefault(plat, []).append(sr)

    existing_plats = set(per_platform.keys())
    all_plats = set(plat_samples.keys())
    missing_plats = all_plats - existing_plats
    if not missing_plats:
        return

    import statistics as stats

    for plat in sorted(missing_plats):
        samples = plat_samples[plat]
        success_rates = [s.get("success_rate_score", 0) for s in samples]
        quality_scores = [s.get("quality_score", 0) for s in samples]
        experience_scores = [s.get("experience_score", 0) for s in samples]
        durations = [s.get("duration_ms", 0) for s in samples if s.get("duration_ms", 0) > 0]
        initial_gen_rates = [s.get("success_rate_score", 0) for s in samples]
        func_completeness = [s.get("functionality_score", 0) for s in samples]
        stability_scores = [s.get("stability_score", 0) for s in samples]
        aesthetics_scores = [s.get("aesthetics_score") for s in samples if s.get("aesthetics_score") is not None]
        token_totals = [s.get("token_total", 0) for s in samples if s.get("token_total", 0) > 0]
        backend_completeness_scores = [
            s.get("backend_completeness")
            for s in samples
            if s.get("requires_backend") and s.get("backend_completeness") is not None
        ]

        total_crashes = sum(s.get("crash_count", 0) for s in samples)
        total_anrs = sum(s.get("anr_count", 0) for s in samples)
        total_white_screens = sum(s.get("white_screen_count", 0) for s in samples)

        e2e_pass = sum(s.get("e2e_pass_count", 0) for s in samples)
        e2e_count = sum(s.get("e2e_total_count", 0) for s in samples)

        plat_metrics = {
            "sample_count": len(samples),
            "mean_success_rate": round(sum(success_rates) / len(success_rates), 1) if success_rates else 0,
            "mean_quality": round(sum(quality_scores) / len(quality_scores), 1) if quality_scores else 0,
            "mean_experience": round(sum(experience_scores) / len(experience_scores), 1) if experience_scores else 0,
            "mean_duration_ms": round(stats.mean(durations), 1) if durations else 0,
            "mean_initial_generation_rate": round(sum(initial_gen_rates) / len(initial_gen_rates), 1) if initial_gen_rates else 0,
            "mean_usecase_completeness": round(sum(func_completeness) / len(func_completeness), 1) if func_completeness else 0,
            "mean_stability_score": round(sum(stability_scores) / len(stability_scores), 1) if stability_scores else 0,
            "mean_aesthetics_score": round(sum(aesthetics_scores) / len(aesthetics_scores), 1) if aesthetics_scores else None,
            "mean_backend_completeness": round(sum(backend_completeness_scores) / len(backend_completeness_scores), 1) if backend_completeness_scores else None,
            "e2e_pass_rate": round(e2e_pass / e2e_count * 100, 1) if e2e_count > 0 else 0,
            "e2e_pass": e2e_pass,
            "e2e_count": e2e_count,
            "total_crashes": total_crashes,
            "total_anrs": total_anrs,
            "total_white_screens": total_white_screens,
            "mean_token_total": round(sum(token_totals) / len(token_totals)) if token_totals else 0,
            "mean_token_input": round(sum(s.get("token_input", 0) for s in samples) / len(samples), 1),
            "mean_token_output": round(sum(s.get("token_output", 0) for s in samples) / len(samples), 1),
        }
        per_platform[plat] = plat_metrics

    if missing_plats:
        logger.info("Backfilled per_platform for missing platforms: %s", sorted(missing_plats))
