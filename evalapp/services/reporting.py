"""Report generation service - business logic extracted from commands/reporting.py.

Handles data processing and persistence during report generation:
- Screenshot extraction and base64 encoding
- Per-sample scores.json writing
- scores_summary.json aggregate writing
- Aesthetics scoring (via unified services.aesthetics entry point)
- Stability log writing
- report.html file management
"""

import base64
import json
import re
from pathlib import Path

from ..utils.logging import get_logger
from ..workspace._safe_io import atomic_write_json

logger = get_logger(__name__)

# 美观度字段：在评分阶段才产出，需回写到 report_data 行供 HTML 报告渲染
_AESTHETICS_REPORT_KEYS = (
    "aesthetics_score", "aesthetics_reason", "aesthetics_issues",
    "aesthetics_dimensions", "aesthetics_rule_version",
    "aesthetics_scored_frames",
)


def _sync_aesthetics_to_row(sr: dict, plat_scores: dict) -> None:
    """将平台评分中的美观度字段回写到 report_data 的样本行。

    build_report_data() 构建 sample_results 时美观度尚未评分，而前端读取的是
    sample_results[*].aesthetics_*，故在写入 scores.json 的同时回填一份。
    源侧为空时不覆盖行上已有的值（report 阶段行上可能已由聚合器填好）。
    """
    for key in _AESTHETICS_REPORT_KEYS:
        value = plat_scores.get(key)
        if value in (None, "", [], {}):
            sr.setdefault(key, value)
        else:
            sr[key] = value


_REBUILT_TOP_LEVEL_METRICS = (
    "mean_success_rate",
    "mean_quality",
    "mean_experience",
    "mean_stability_score",
    "mean_duration_ms",
    "mean_aesthetics_score",
)


def _sync_rebuilt_top_level_metrics(report_data: dict, rebuilt: dict) -> bool:
    """将包含失败样本的重聚合指标整体同步到报告顶层。"""
    rebuilt_tls = rebuilt.get("top_level_summary", {}) or {}
    rebuilt_per_platform = rebuilt_tls.get("per_platform", {})
    tls = report_data.get("top_level_summary", {})
    if not rebuilt_per_platform or not tls:
        return False

    tls["per_platform"] = rebuilt_per_platform
    for metric in _REBUILT_TOP_LEVEL_METRICS:
        if metric in rebuilt_tls:
            tls[metric] = rebuilt_tls[metric]
    return True


class ReportService:
    """Report generation service.

    Encapsulates data processing and file I/O operations during report
    generation, so that commands/reporting.py only focuses on CLI argument
    parsing, workflow orchestration, and output display.
    """

    def __init__(self, workspace: Path, config=None):
        self.workspace = Path(workspace)
        self.config = config

    def extract_screenshots_for_report(self, report_data: dict, *, save_to_disk: bool = False) -> None:
        """Extract screenshot data for each sample in report_data.

        Injects screenshot data directly into items in report_data["sample_results"].
        Prefers already-saved screenshot files under the sample directory;
        otherwise extracts from E2E report HTML.

        [Performance optimization] When a screenshot already exists as a file,
        sets the _screenshot_file_rel_path field so that downstream
        write_scores_files() uses the path directly, avoiding redundant
        base64 decode-then-rewrite of the same file.

        Args:
            report_data: In-memory report_data dict (modified in place).
            save_to_disk: Save extracted screenshots to disk immediately
                (workspace mode needs this for the frontend API to read).
        """
        from evalapp.evaluation.results.comparison.screenshot_extractor import (
            extract_sample_screenshot,
            extract_sample_all_screenshots,
        )

        e2e_reports_dir = self.workspace / "e2e_reports"

        for sr in report_data.get("sample_results", []):
            sample_id = sr.get("sample_id", "")
            platform = sr.get("platform", "")

            # --- 启动截图 ---
            screenshots_dir = self.workspace / sample_id / "screenshots"
            launch_screenshot_file = screenshots_dir / f"launch_{platform}.png"
            if not launch_screenshot_file.exists():
                launch_screenshot_file = screenshots_dir / f"launch_{platform}.jpg"

            if launch_screenshot_file.exists():
                img_bytes = launch_screenshot_file.read_bytes()
                ext = launch_screenshot_file.suffix.lstrip(".")
                mime = "image/jpeg" if ext == "jpg" else f"image/{ext}"
                b64_data = base64.b64encode(img_bytes).decode("ascii")
                sr["launch_screenshot"] = f"data:{mime};base64,{b64_data}"
                sr["screenshot_source"] = "screenshots_dir"
                sr["screenshot_reason"] = f"来自 {sample_id}/screenshots/{launch_screenshot_file.name}"
                # [性能优化] 记录文件相对路径，避免 write_scores_files 重复解码写入
                sr["_screenshot_file_rel_path"] = f"screenshots/{launch_screenshot_file.name}"
            else:
                screenshot_result = extract_sample_screenshot(e2e_reports_dir, sample_id, platform)
                if not screenshot_result.get("screenshot"):
                    sample_e2e_dir = self.workspace / sample_id / "e2e_reports"
                    screenshot_result = extract_sample_screenshot(sample_e2e_dir, sample_id, platform)
                sr["launch_screenshot"] = screenshot_result.get("screenshot")
                sr["screenshot_source"] = screenshot_result.get("source")
                sr["screenshot_reason"] = screenshot_result.get("reason")
                # 提取后写入文件，供前端 API 直接读取
                if save_to_disk and screenshot_result.get("screenshot") and screenshot_result["screenshot"].startswith("data:image/"):
                    saved_path = self._save_screenshot_file(sample_id, platform, screenshot_result["screenshot"])
                    if saved_path:
                        sr["_screenshot_file_rel_path"] = saved_path

            # --- fallback: 美学截图兜底 ---
            if not sr.get("launch_screenshot"):
                step1_file = screenshots_dir / "step_1.jpg"
                if not step1_file.exists():
                    step1_file = screenshots_dir / "step_1.png"
                if step1_file.exists():
                    img_bytes = step1_file.read_bytes()
                    ext = step1_file.suffix.lstrip(".")
                    mime = "image/jpeg" if ext == "jpg" else f"image/{ext}"
                    b64_data = base64.b64encode(img_bytes).decode("ascii")
                    sr["launch_screenshot"] = f"data:{mime};base64,{b64_data}"
                    sr["screenshot_source"] = "aesthetics_fallback"
                    sr["screenshot_reason"] = f"launch截图缺失，兜底使用 {sample_id}/screenshots/{step1_file.name}"
                    sr["_screenshot_file_rel_path"] = f"screenshots/{step1_file.name}"

            # --- 所有截图 ---
            all_shots = extract_sample_all_screenshots(e2e_reports_dir, sample_id, platform)
            if not all_shots:
                sample_e2e_dir = self.workspace / sample_id / "e2e_reports"
                all_shots = extract_sample_all_screenshots(sample_e2e_dir, sample_id, platform)

            if not all_shots and screenshots_dir.exists():
                for shot_file in sorted(screenshots_dir.iterdir()):
                    if shot_file.is_file() and shot_file.suffix.lower() in (".png", ".jpg", ".jpeg"):
                        img_bytes = shot_file.read_bytes()
                        ext = shot_file.suffix.lstrip(".")
                        mime = "image/jpeg" if ext == "jpg" else f"image/{ext}"
                        b64_data = base64.b64encode(img_bytes).decode("ascii")
                        all_shots.append({
                            "url": f"data:{mime};base64,{b64_data}",
                            "step_name": shot_file.stem,
                        })

            sr["screenshots"] = all_shots

    def write_scores_files(self, report_data: dict, *, parallel: bool = False, skip_aesthetics: bool = False) -> dict[str, dict]:
        """Write scores from report_data into each sample's scores.json and run aesthetics scoring.

        Args:
            report_data: In-memory report_data dict.
            parallel: Whether to run aesthetics scoring in parallel (workspace mode optimization).
            skip_aesthetics: Skip new aesthetics scoring (used in report phase; preserves existing scores only).

        Returns:
            seen_samples: {sample_id: {...}} information about processed samples.
        """
        from ..workspace.sample_data import write_scores
        from . import aesthetics as aesthetics_svc

        rules = aesthetics_svc.load_rules()
        seen_samples: dict[str, dict] = {}

        if parallel and rules:
            return self._write_scores_files_parallel(report_data, rules, skip_aesthetics=skip_aesthetics)

        for sr in report_data.get("sample_results", []):
            sample_id = sr["sample_id"]
            platform = sr["platform"]

            # 读取现有 scores.json 或创建新的
            scores_path = self.workspace / sample_id / "scores.json"
            if scores_path.exists():
                scores = json.loads(scores_path.read_text())
            else:
                scores = {"sample_id": sample_id, "platforms": {}}

            # 保存截图文件
            # [性能优化] 优先使用 extract_screenshots 阶段记录的文件路径，
            # 避免将已存在的截图 base64 解码后再次写入同一文件（双重IO）
            screenshot_path = ""
            _cached_rel_path = sr.get("_screenshot_file_rel_path", "")
            if _cached_rel_path:
                screenshot_path = _cached_rel_path
            else:
                launch_screenshot = sr.get("launch_screenshot", "")
                if launch_screenshot and launch_screenshot.startswith("data:image/"):
                    screenshot_path = self._save_screenshot_file(sample_id, platform, launch_screenshot)
                elif launch_screenshot:
                    screenshot_path = launch_screenshot

            # 美观度评分（优先复用已有结果）
            aesthetics_data = None
            existing_aesthetics = scores.get("platforms", {}).get(platform, {}).get("aesthetics_score")
            if existing_aesthetics is None and rules and not skip_aesthetics:
                app_category = sr.get("top_category", "")
                aesthetics_data = aesthetics_svc.score_sample(
                    self.workspace, sample_id, platform, app_category, rules,
                    config=self.config,
                )

            # 优先保留 evaluate 阶段已写入的后端字段
            existing_platform = scores.get("platforms", {}).get(platform, {})
            scores["platforms"][platform] = {
                "success_rate_score": sr.get("success_rate_score", 0),
                "quality_score": sr.get("quality_score", 0),
                "experience_score": sr.get("experience_score", 0),
                "stability_score": sr.get("stability_score", 0),
                "launch_screenshot": screenshot_path,
                "requires_backend": existing_platform.get("requires_backend", sr.get("requires_backend", False)),
                "backend_completeness": existing_platform.get("backend_completeness", sr.get("backend_completeness")),
                "backend_completeness_reason": existing_platform.get("backend_completeness_reason", sr.get("backend_completeness_reason", "")),
                "backend_requests": existing_platform.get("backend_requests", sr.get("backend_requests", [])),
                "aesthetics_score": aesthetics_data["aesthetics_score"] if aesthetics_data else existing_platform.get("aesthetics_score"),
                "aesthetics_reason": aesthetics_data["aesthetics_reason"] if aesthetics_data else existing_platform.get("aesthetics_reason", ""),
                "aesthetics_issues": aesthetics_data["aesthetics_issues"] if aesthetics_data else existing_platform.get("aesthetics_issues", []),
                "aesthetics_dimensions": aesthetics_data["aesthetics_dimensions"] if aesthetics_data else existing_platform.get("aesthetics_dimensions", {}),
                "aesthetics_rule_version": aesthetics_data["aesthetics_rule_version"] if aesthetics_data else existing_platform.get("aesthetics_rule_version", ""),
                "aesthetics_scored_frames": aesthetics_data["aesthetics_scored_frames"] if aesthetics_data else existing_platform.get("aesthetics_scored_frames", []),
            }
            write_scores(self.workspace, sample_id, scores)
            _sync_aesthetics_to_row(sr, scores["platforms"][platform])

            # 跟踪已处理的样本
            if sample_id not in seen_samples:
                seen_samples[sample_id] = {"sample_id": sample_id, "platforms": [], "scores_path": f"{sample_id}/scores.json"}
            if platform not in seen_samples[sample_id]["platforms"]:
                seen_samples[sample_id]["platforms"].append(platform)

        return seen_samples

    def write_scores_summary(self, report_data: dict, seen_samples: dict[str, dict], *, schema_version: str = "") -> None:
        """Write the scores_summary.json aggregate file.

        Args:
            report_data: In-memory report_data dict.
            seen_samples: Processed sample information returned by write_scores_files().
            schema_version: Optional schema version string (workspace mode passes "2.0").
        """
        from ..workspace.report_data import write_scores_summary

        scores_summary_meta = report_data.get("meta", {})
        # 确保 meta 包含 platform 字符串格式
        if "platform" not in scores_summary_meta or not scores_summary_meta.get("platform"):
            platforms = scores_summary_meta.get("platforms", [])
            if platforms and isinstance(platforms, list):
                scores_summary_meta["platform"] = ",".join(platforms)

        # 合并已处理样本与被排除样本，确保 samples 数组反映全部计划样本。
        # 被排除样本同样拥有 scores.json（由 evaluator 阶段写入），应被下游统计。
        all_samples: dict[str, dict] = dict(seen_samples)
        excluded_samples = report_data.get("excluded_samples")
        if excluded_samples:
            for exc in excluded_samples:
                sid = exc.get("sample_id")
                if not sid or sid in all_samples:
                    continue
                plat_raw = exc.get("platform", "")
                platforms = [p.strip() for p in str(plat_raw).split(",") if p.strip()]
                all_samples[sid] = {
                    "sample_id": sid,
                    "platforms": platforms,
                    "scores_path": f"{sid}/scores.json",
                    "excluded": True,
                }

        scores_summary = {
            "meta": scores_summary_meta,
            "summary": report_data.get("summary", {}),
            "top_level_summary": report_data.get("top_level_summary", {}),
            "cross_platform_comparison": report_data.get("cross_platform_comparison", {}),
            "samples": list(all_samples.values()),
        }
        # 将 manifest 过滤舍弃的“未完成/已舍弃”样本一并写入汇总文件，
        # 便于下游区分 completed 与被排除项。
        if excluded_samples:
            scores_summary["excluded_samples"] = excluded_samples
        if schema_version:
            scores_summary["schema_version"] = schema_version
        write_scores_summary(self.workspace, scores_summary)
        logger.info("Wrote scores_summary.json")

    def write_stability_data(self) -> None:
        """Write stability logs to the report/stability/ directory."""
        from ..workspace.report_data import write_stability as _write_stability

        for sample_d in self.workspace.iterdir():
            if not sample_d.is_dir() or sample_d.name.startswith("."):
                continue
            stab_dir = sample_d / "stability_logs"
            if not stab_dir.exists():
                continue
            for gen_dir in stab_dir.iterdir():
                if gen_dir.is_dir():
                    crash_file = gen_dir / "crash_anr_events.json"
                    if crash_file.exists():
                        data = json.loads(crash_file.read_text())
                        _write_stability(self.workspace, sample_d.name, data)

    def copy_report_html(self) -> None:
        """Copy report.html to the report/ subdirectory."""
        import shutil

        report_dir = self.workspace / "report"
        report_dir.mkdir(parents=True, exist_ok=True)
        old_report = self.workspace / "report.html"
        new_report = report_dir / "report.html"
        if old_report.exists() and not new_report.exists():
            shutil.copy2(old_report, new_report)
            logger.info("Copied report.html to report/report.html")

    def _write_scores_files_parallel(self, report_data: dict, rules: dict, *, skip_aesthetics: bool = False) -> dict[str, dict]:
        """并行版 write_scores_files - 使用 ThreadPoolExecutor 加速 AI 美观度评分。

        workspace mode 数据量大时使用此优化路径，避免样本间串行等待。
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from ..workspace.sample_data import write_scores
        from ..evaluation.metrics.collectors.aesthetics import score_aesthetics
        from ..evaluation.metrics.collectors.aesthetics_frames import select_key_frames

        seen_samples: dict[str, dict] = {}
        samples_needing_scoring: list[tuple[int, dict, dict]] = []
        all_scores_data: list[tuple[dict, dict, str]] = []

        # Phase 1: 收集所有样本数据 + 判断哪些需要 AI 评分
        for idx, sr in enumerate(report_data.get("sample_results", [])):
            sample_id = sr["sample_id"]
            platform = sr["platform"]
            scores_path = self.workspace / sample_id / "scores.json"
            if scores_path.exists():
                scores = json.loads(scores_path.read_text())
            else:
                scores = {"sample_id": sample_id, "platforms": {}}

            # 截图路径
            screenshot_path = ""
            _cached_rel = sr.get("_screenshot_file_rel_path", "")
            if _cached_rel:
                screenshot_path = _cached_rel
            else:
                launch_screenshot = sr.get("launch_screenshot", "")
                if launch_screenshot and launch_screenshot.startswith("data:image/"):
                    screenshot_path = self._save_screenshot_file(sample_id, platform, launch_screenshot)
                elif launch_screenshot:
                    screenshot_path = launch_screenshot

            all_scores_data.append((sr, scores, screenshot_path))

            # 判断是否需要 AI 评分
            existing_aesthetics = scores.get("platforms", {}).get(platform, {}).get("aesthetics_score")
            if existing_aesthetics is None and not skip_aesthetics:
                sample_dir = self.workspace / sample_id
                frames = select_key_frames(str(sample_dir), platform)
                if frames:
                    samples_needing_scoring.append((idx, sr, {
                        "sample_dir": sample_dir,
                        "platform": platform,
                        "app_category": sr.get("top_category", ""),
                    }))

        # Phase 2: 并行执行 AI 美观度评分
        aesthetics_results: dict[int, object] = {}
        if samples_needing_scoring:
            def _score_one(item):
                idx, sr, params = item
                try:
                    from .aesthetics import _build_model_config
                    model_config = _build_model_config(self.config)
                    result = score_aesthetics(
                        sample_dir=str(params["sample_dir"]),
                        platform=params["platform"],
                        app_category=params["app_category"],
                        model_config=model_config,
                    )
                    return idx, result
                except Exception:
                    return idx, None

            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = [pool.submit(_score_one, item) for item in samples_needing_scoring]
                for future in as_completed(futures):
                    idx, result = future.result()
                    if result is not None:
                        aesthetics_results[idx] = result

        # Phase 3: 写入 scores.json
        for idx, (sr, scores, screenshot_path) in enumerate(all_scores_data):
            sample_id = sr["sample_id"]
            platform = sr["platform"]
            aes_result = aesthetics_results.get(idx)

            existing_platform = scores.get("platforms", {}).get(platform, {})
            scores["platforms"][platform] = {
                "success_rate_score": sr.get("success_rate_score", 0),
                "quality_score": sr.get("quality_score", 0),
                "experience_score": sr.get("experience_score", 0),
                "stability_score": sr.get("stability_score", 0),
                "launch_screenshot": screenshot_path,
                "requires_backend": existing_platform.get("requires_backend", sr.get("requires_backend", False)),
                "backend_completeness": existing_platform.get("backend_completeness", sr.get("backend_completeness")),
                "backend_completeness_reason": existing_platform.get("backend_completeness_reason", sr.get("backend_completeness_reason", "")),
                "backend_requests": existing_platform.get("backend_requests", sr.get("backend_requests", [])),
                "aesthetics_score": aes_result.overall if aes_result else existing_platform.get("aesthetics_score"),
                "aesthetics_reason": aes_result.comment if aes_result else existing_platform.get("aesthetics_reason", ""),
                "aesthetics_issues": aes_result.issues if aes_result else existing_platform.get("aesthetics_issues", []),
                "aesthetics_dimensions": aes_result.dimensions if aes_result else existing_platform.get("aesthetics_dimensions", {}),
                "aesthetics_rule_version": aes_result.rule_version if aes_result else existing_platform.get("aesthetics_rule_version", ""),
                "aesthetics_scored_frames": aes_result.scored_frames if aes_result else existing_platform.get("aesthetics_scored_frames", []),
            }
            write_scores(self.workspace, sample_id, scores)
            _sync_aesthetics_to_row(sr, scores["platforms"][platform])

            if sample_id not in seen_samples:
                seen_samples[sample_id] = {"sample_id": sample_id, "platforms": [], "scores_path": f"{sample_id}/scores.json"}
            if platform not in seen_samples[sample_id]["platforms"]:
                seen_samples[sample_id]["platforms"].append(platform)

        return seen_samples

    def _save_screenshot_file(self, sample_id: str, platform: str, data_url: str) -> str:
        """将 base64 截图保存为文件，返回相对路径。"""
        try:
            match = re.match(r"data:image/(\w+);base64,(.+)", data_url)
            if not match:
                return ""

            img_format = match.group(1)
            img_data = match.group(2)
            ext = "jpg" if img_format == "jpeg" else img_format

            screenshots_dir = self.workspace / sample_id / "screenshots"
            screenshots_dir.mkdir(parents=True, exist_ok=True)

            filename = f"launch_{platform}.{ext}"
            filepath = screenshots_dir / filename
            filepath.write_bytes(base64.b64decode(img_data))

            return f"screenshots/{filename}"
        except Exception:
            return ""

    # ===================== 报告生成入口 =====================

    def run_report(
        self,
        run,
        dataset_version: str,
        *,
        only_export_pairs=None,
        no_open_report: bool = False,
        console=None,
    ) -> Path:
        """Core report generation workflow after evaluation (replaces commands/reporting.do_report internals).

        Responsible for:
        - Filtering incomplete/failed samples from the manifest
        - Creating run records
        - Exporting E2E reports / building in-memory report_data / screenshot extraction
        - HTML report rendering, scores.json/scores_summary.json writing
        - Stability log writing and report.html copying

        Args:
            run: EvalRun object (filtered in place).
            dataset_version: Dataset version string.
            only_export_pairs: Optional, restrict export_e2e_reports to specific (item, platform) pairs.
            no_open_report: Disable automatic browser opening.
            console: Optional Rich Console for output; None for silent.

        Returns:
            output_dir: Report output directory (i.e., the workspace).
        """
        import webbrowser
        from . import report_backfill as backfill
        from ..evaluation.results.models import build_report_data as _build_report_data
        from ..evaluation.results.reporting import Reporter
        from ..evaluation.results.store import ResultStore
        from ..utils.files import round_scores
        from ..workspace.runs import create_run, finish_run

        workspace_dir = self.workspace
        config = self.config

        def _say(msg: str) -> None:
            if console is not None:
                console.print(msg)

        result_store = ResultStore(workspace_dir)

        # === 部分成功报告：从 execution_manifest.json 排除 failed/skipped 样本 ===
        excluded_pairs: dict[tuple[str, str], str] = {}
        excluded_summary: list[dict] = []
        manifest_info = backfill.load_manifest_exclusions(workspace_dir)
        if manifest_info is not None:
            excluded_pairs, sample_overall = manifest_info
            if excluded_pairs:
                kept, dropped = backfill.filter_run_by_manifest(run, excluded_pairs)
                excluded_summary = backfill.build_excluded_summary(
                    excluded_pairs, sample_overall,
                )
                logger.info(
                    "Manifest 过滤: 保留 %d 个 completed 样本×平台，舍弃 %d 个 failed/skipped 项",
                    kept, dropped,
                )
                _say(
                    f"  部分数据报告：从 manifest 舍弃 {dropped} 个未完成/失败项，仅纳入 {kept} 项进入评分"
                )
                if kept == 0:
                    logger.warning(
                        "所有样本均被 manifest 标记为 failed/skipped，无可用评分数据，跳过报告生成"
                    )
                    _say("  ⚠️ 所有样本均失败/跳过，跳过报告生成")
                    return workspace_dir
                try:
                    run.compute_summary(workspace_path=self.workspace)
                except Exception as exc:
                    logger.warning("过滤后重新计算 summary 失败：%s", exc)

        # 创建 run 记录
        run_dir = None
        try:
            run_dir = create_run(workspace_dir, phase="report")
        except Exception as e:
            logger.warning("Failed to create run record: %s", e)

        output_dir = workspace_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        # 导出 E2E 报告
        exported_reports = result_store.export_e2e_reports(
            run, output_dir, only_pairs=only_export_pairs,
        )
        if exported_reports:
            _say(f"  E2E 报告: 已导出 {len(exported_reports)} 份到各样本目录下")

        # 在内存中构建 report_data
        _rd_obj = _build_report_data(run)
        _rd_obj.meta.dataset_version = dataset_version
        _rd_obj.meta.eval_version = config.report.eval_version
        report_data = round_scores(_rd_obj.model_dump())

        if excluded_summary:
            report_data["excluded_samples"] = excluded_summary

        # 截图提取（HTML 报告在全部数据补全后统一渲染，见下方）
        self.extract_screenshots_for_report(report_data)

        # 稳定性日志导出
        exported_stability = result_store.export_stability_logs(run, output_dir)
        if exported_stability:
            _say(f"  稳定性日志: 已导出 {len(exported_stability)} 份到各样本目录下")

        # 补全 top_level_summary 中的聚合指标（如美观度等）
        backfill.backfill_per_platform_from_sample_results(report_data)

        # 跨平台一致性对比
        from .cross_platform import enrich_report_data_with_cross_platform
        enrich_report_data_with_cross_platform(report_data, workspace_dir)

        # 生成分析汇总报告（仅配置名单中的生成器）
        try:
            from ..diagnosis.analyzer import SampleAnalyzer
            _analysis_generators = getattr(config, 'sample_analysis_generators', []) or []
            if run.generator_name and run.generator_name in _analysis_generators:
                SampleAnalyzer.summarize(workspace_dir)
        except Exception as exc:
            logger.warning("Analysis summary generation failed: %s", exc)

        # 修正: 当存在 excluded_samples 时，从原始 scores.json 重新聚合
        # per_platform 指标，确保失败样本的 0 分也计入平台均值。
        if excluded_summary:
            try:
                from .report_rebuild import rebuild_report_data_from_samples
                rebuilt = rebuild_report_data_from_samples(workspace_dir)
                if rebuilt is not None:
                    if _sync_rebuilt_top_level_metrics(report_data, rebuilt):
                        logger.info("已从原始 scores.json 重新聚合顶层及 per_platform 指标（含 excluded 样本）")
            except Exception as exc:
                logger.warning("重新聚合 per_platform 失败: %s", exc)

        # 写入新格式 scores 文件
        seen_samples: dict[str, dict] = {}
        try:
            seen_samples = self.write_scores_files(report_data)
            self.write_scores_summary(report_data, seen_samples)
            logger.info("Wrote new format scores files")
        except Exception as e:
            logger.error(
                "新格式 scores 文件写入失败：%s",
                e,
                exc_info=True,
            )

        # 合并各样本的分散数据到自包含 sample_report.json
        try:
            from ..workspace.sample_data import consolidate_all_sample_reports
            consolidate_all_sample_reports(self.workspace)
            logger.info("Consolidated all sample_report.json files")
        except Exception as e:
            logger.warning("Failed to consolidate sample_report.json files: %s", e)

        # 执行概览分析（429错误统计与子Agent分析）
        try:
            import sys as _sys
            _scripts_dir = str(Path(__file__).resolve().parent.parent.parent / "scripts")
            if _scripts_dir not in _sys.path:
                _sys.path.insert(0, _scripts_dir)
            from analyze_execution import analyze_workspace as _analyze_workspace
            result = _analyze_workspace(str(workspace_dir))
            if isinstance(result, dict) and result:
                # 同步带入报告数据，静态报告页“执行总览”区块直接消费
                report_data["execution_overview"] = result
                # 持久化到工作区，评测完成时即生成，避免依赖报告页兜底现算；写失败不中断报告流程
                overview_path = Path(workspace_dir) / "execution_overview.json"
                try:
                    atomic_write_json(overview_path, result, ensure_ascii=False, indent=2)
                except Exception as e:
                    logger.warning("执行概览写入失败 %s: %s", overview_path, e)
        except Exception as exc:
            logger.exception("执行概览分析失败: %s", exc)

        # [DEPRECATED] report_data.json 写入已废弃，新格式请使用 scores_summary.json

        # HTML 报告渲染（前端单文件模板注入，数据与 Web 控制台报告页一致）
        try:
            from ..evaluation.results.reporting.reporter import _truncate_case_details
            backfill.migrate_e2e_report_paths(report_data, workspace_dir)
            _truncate_case_details(report_data)
            html = Reporter().render_html_from_data(report_data, workspace_dir=output_dir)
            html_path = output_dir / "report.html"
            html_path.write_text(html, encoding="utf-8")
            _say(f"  HTML: {html_path}")
        except Exception as e:
            logger.error("HTML 报告渲染失败: %s", e, exc_info=True)

        # stability 写入新位置
        try:
            self.write_stability_data()
        except Exception as e:
            logger.warning("Failed to write stability data to new location: %s", e)

        # report.html 复制到 report/
        try:
            self.copy_report_html()
        except Exception as e:
            logger.warning("Failed to copy report.html to new location: %s", e)

        # 自动打开浏览器
        if not no_open_report and config.report.auto_open:
            html_path = output_dir / "report.html"
            if html_path.exists():
                webbrowser.open(f"file://{html_path}")
                _say("  已在浏览器中打开报告")

        # 自动分析（已下线）：旧 Go 分析器已被
        # 新的 Python SampleAnalyzer (evalapp/diagnosis/) 替代。

        # 结束 run 记录
        if run_dir:
            try:
                finish_run(run_dir, exit_code=0, result_summary={
                    "phase": "report",
                    "total_tasks": len(seen_samples),
                    "succeeded": len(seen_samples),
                    "failed": 0,
                    "skipped": 0,
                    "samples_affected": list(seen_samples.keys()),
                })
            except Exception as e:
                logger.warning("Failed to finish run record: %s", e)

        return output_dir

    def regenerate_workspace_report(
        self,
        *,
        no_open_report: bool = False,
        console=None,
        report_data: dict | None = None,
        write_report_data: bool = False,
    ) -> Path | None:
        """Regenerate the HTML summary report in workspace mode.

        Prefers the provided report_data; otherwise aggregates dynamically
        from sample data via the aggregator; falls back to report_data.json.

        Returns:
            HTML report path, or None if report data is unavailable.
        """
        import webbrowser
        from . import report_backfill as backfill
        from ..evaluation.results.reporting import Reporter
        from ..utils.files import round_scores
        from ..utils.json_io import read_json as _read_json
        from ..workspace._safe_io import atomic_write_text

        workspace = self.workspace
        config = self.config

        def _say(msg: str) -> None:
            if console is not None:
                console.print(msg)

        # 优先使用传入的 report_data，否则尝试聚合器，最后回退到 report_data.json
        if report_data is not None:
            report_data_raw = report_data
        else:
            from .report_aggregator import aggregate_report
            report_data_raw = aggregate_report(workspace)
            if report_data_raw is None:
                # 回退：先尝试从 report_data.json 读取（旧格式兼容）
                report_data_file = workspace / "report_data.json"
                if report_data_file.exists():
                    report_data_raw = _read_json(report_data_file)

                # 兼容路径：如果 report_data.json 不存在但 run_data.json 存在，
                # 从 run_data.json 在内存中生成报告数据（不再写入 report_data.json）
                if report_data_raw is None:
                    run_data_file = workspace / "run_data.json"
                    if run_data_file.exists():
                        import warnings
                        warnings.warn(
                            "从 run_data.json 生成报告数据的兼容路径已废弃，将在 v3.0 移除。"
                            "请使用新格式（scores.json + scores_summary.json）。",
                            DeprecationWarning,
                            stacklevel=2,
                        )
                        logger.warning(
                            "[DEPRECATED] 正在从旧格式 run_data.json 生成报告数据（仅内存使用），"
                            "此兼容路径将在 v3.0 移除: %s", run_data_file,
                        )
                        from evalapp.evaluation.results.models import EvalRun, build_report_data
                        run_raw = _read_json(run_data_file)
                        gen_name = run_raw.get("generator_name", "unknown")
                        run_id = run_raw.get("run_id", "unknown")
                        for pr in run_raw.get("prompt_results", []):
                            pr.setdefault(
                                "prompt_id",
                                pr.get("sample_id", f"{run_id}_{pr.get('platform', 'unknown')}"),
                            )
                            pr.setdefault("generator_name", gen_name)
                        run_obj = EvalRun(**run_raw)
                        report_data_obj = build_report_data(run_obj)
                        report_data_raw = round_scores(report_data_obj.model_dump())
                        logger.info("从 run_data.json 在内存中生成报告数据（不再写入磁盘）")

        if report_data_raw is None:
            return None

        # 部分成功报告：从 manifest 排除 failed/skipped 样本
        excluded_pairs: dict[tuple[str, str], str] = {}
        excluded_summary: list[dict] = []
        manifest_info = backfill.load_manifest_exclusions(workspace)
        if manifest_info is not None:
            excluded_pairs, sample_overall = manifest_info
            if excluded_pairs:
                dropped = backfill.filter_report_data_by_manifest(
                    report_data_raw, excluded_pairs,
                )
                excluded_summary = backfill.build_excluded_summary(
                    excluded_pairs, sample_overall,
                )
                if dropped:
                    _say(
                        f"  部分数据报告：从 manifest 舍弃 {dropped} 个未完成/失败项"
                    )
        if excluded_summary:
            report_data_raw["excluded_samples"] = excluded_summary

        eval_version = config.report.eval_version
        report_data_raw["eval_version"] = eval_version
        if "meta" in report_data_raw:
            report_data_raw["meta"]["eval_version"] = eval_version

        # 共享 sample_report.json 缓存供多个 backfill 使用
        _sr_cache = backfill.load_sample_report_cache(workspace)
        backfill.backfill_duration_from_sample_reports(report_data_raw, workspace, _cache=_sr_cache)
        backfill.backfill_platform_token(report_data_raw)
        backfill.backfill_platform_e2e(report_data_raw)
        backfill.backfill_per_platform_from_sample_results(report_data_raw)
        backfill.backfill_package_size_from_sample_reports(report_data_raw, workspace, _cache=_sr_cache)

        # 跨平台一致性对比
        from .cross_platform import enrich_report_data_with_cross_platform
        enrich_report_data_with_cross_platform(report_data_raw, workspace)

        report_data_raw["meta"]["workspace_name"] = str(workspace)
        if self.config:
            report_data_raw["meta"]["generator_branch"] = getattr(self.config.generator, "branch", "") or ""

        # 截图提取 + scores 写入
        self.extract_screenshots_for_report(report_data_raw, save_to_disk=True)
        seen_samples = self.write_scores_files(report_data_raw, parallel=True, skip_aesthetics=True)

        # 合并各样本的分散数据到自包含 sample_report.json
        try:
            from ..workspace.sample_data import consolidate_all_sample_reports
            consolidate_all_sample_reports(workspace)
            logger.info("Consolidated all sample_report.json files (workspace mode)")
        except Exception as e:
            logger.warning("Failed to consolidate sample_report.json files (workspace mode): %s", e)

        # 迁移旧绝对路径 report_path 为相对路径
        backfill.migrate_e2e_report_paths(report_data_raw, workspace)
        backfill.backfill_stability_detail_from_evaluation(report_data_raw, workspace)

        # 清理 details 字段，避免嵌入JS时引号/转义导致语法错误
        for sr in report_data_raw.get("sample_results", []):
            for case in sr.get("e2e_test_cases", []):
                if "details" in case and case["details"]:
                    detail = case["details"]
                    for marker in ["\n    at ", "\nError:"]:
                        idx = detail.find(marker)
                        if idx > 0:
                            detail = detail[:idx]
                            break
                    if len(detail) > 200:
                        detail = detail[:200] + "..."
                    case["details"] = detail

        # [DEPRECATED] report_data.json 写入已废弃，新格式请使用 scores_summary.json
        if write_report_data:
            logger.warning(
                "[DEPRECATED] write_report_data=True 已废弃，report_data.json 不再写入。"
                "新格式使用 scores_summary.json。",
            )

        # 修正: 当存在 excluded_samples 时，从原始 scores.json 重新聚合
        # per_platform 指标，确保失败样本的 0 分也计入平台均值。
        if excluded_summary:
            try:
                from .report_rebuild import rebuild_report_data_from_samples
                rebuilt = rebuild_report_data_from_samples(workspace)
                if rebuilt is not None:
                    if _sync_rebuilt_top_level_metrics(report_data_raw, rebuilt):
                        logger.info("已从原始 scores.json 重新聚合顶层及 per_platform 指标（workspace mode，含 excluded 样本）")
            except Exception as exc:
                logger.warning("重新聚合 per_platform 失败 (workspace mode): %s", exc)

        # 同步写入新格式 scores_summary.json
        try:
            self.write_scores_summary(report_data_raw, seen_samples, schema_version="2.0")
        except Exception as e:
            logger.warning("Failed to write scores_summary.json in workspace mode: %s", e)

        html = Reporter().render_html_from_data(report_data_raw, workspace_dir=workspace)
        html_path = workspace / "report.html"
        atomic_write_text(html_path, html)
        _say(f"  HTML: {html_path}")
        if not no_open_report and config.report.auto_open:
            webbrowser.open(f"file://{html_path}")
            _say("  已在浏览器中打开报告")

        return html_path
