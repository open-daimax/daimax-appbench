"""ResultStore: persists evaluation run results as JSON."""

from __future__ import annotations

import json
import re
import shutil
import warnings
from datetime import datetime
from pathlib import Path

from ...utils.logging import get_logger
from ...workspace._safe_io import atomic_write_json
from .models import EvalRun

logger = get_logger(__name__)


_UNSAFE_NAME_CHARS = re.compile(r"[^A-Za-z0-9._-]+")
# 当 sanitise 后的安全名与原名不一致时，附加一个短哈希后缀，避免不同
# sample_id 被 sanitise 为同一文件名造成数据覆盖（W-07）。
_NAME_HASH_LEN = 8

# Directory names that are known to be *shared* report roots, i.e. the
# same folder is reused across runs and accumulates historical reports.
# When ``report.html`` lives directly under one of these, we must only
# copy that single file – never the whole folder – otherwise unrelated
# older reports would be dragged into the evaluation output.
_SHARED_REPORT_DIRS = {"report", "reports", "midscene_run"}

# File extensions that count as "report" documents when we detect
# whether a folder is shared (contains many reports) vs. per-case.
_REPORT_FILE_EXTS = {".html", ".htm"}

# Sharded storage constants
_META_FILENAME = "meta.json"
_SHARD_SEPARATOR = "__"  # separator in shard filenames when sample_id contains unsafe chars


def _sanitise_name(value: str, fallback: str = "unknown") -> str:
    """Turn an arbitrary string into a filesystem-friendly token."""
    cleaned = _UNSAFE_NAME_CHARS.sub("_", (value or "").strip()).strip("._-")
    return cleaned or fallback


def _is_shared_report_dir(folder: Path) -> bool:
    """Return True if *folder* looks like a shared report directory.

    Heuristics:
    * Folder name matches a known shared root (``report``/``reports``/
      ``midscene_run``), OR
    * Folder contains more than one ``*.html`` file – a clear sign it is
      an aggregation directory rather than a single-case bundle.
    """
    try:
        if folder.name.lower() in _SHARED_REPORT_DIRS:
            return True
        html_count = sum(
            1 for child in folder.iterdir()
            if child.is_file() and child.suffix.lower() in _REPORT_FILE_EXTS
        )
        return html_count > 1
    except OSError:
        # If we cannot inspect the folder, err on the safe side.
        return True


class ResultStore:
    """Manages evaluation result storage on disk.

    Storage layout (flat, default):
        results/{run_id}.json

    Storage layout (sharded, opt-in):
        results/{run_id}/meta.json        – run metadata (no prompt_results)
        results/{run_id}/{sample_id}.json – per-sample prompt_results list

    Reading always tries the sharded path first and falls back to the
    flat layout, ensuring full backward compatibility.
    """

    def __init__(self, results_dir: Path) -> None:
        self.results_dir = results_dir

    # ------------------------------------------------------------------
    # Sharded path helpers
    # ------------------------------------------------------------------

    def _shard_dir(self, run_id: str) -> Path:
        """Return the shard directory for *run_id*."""
        return self.results_dir / run_id

    def _shard_meta_path(self, run_id: str) -> Path:
        """Return the meta.json path inside a shard directory."""
        return self._shard_dir(run_id) / _META_FILENAME

    def _shard_sample_path(self, run_id: str, sample_id: str) -> Path:
        """
        Return the per-sample JSON path inside a shard directory.

        The sample_id is sanitised so the filename is filesystem-safe.
        """
        safe_name = _sanitise_name(sample_id, "unknown")
        return self._shard_dir(run_id) / f"{safe_name}.json"

    def _is_sharded(self, run_id: str) -> bool:
        """Return True if *run_id* is stored in sharded layout."""
        return self._shard_meta_path(run_id).exists()

    def _load_sharded(self, run_id: str) -> EvalRun | None:
        """Load a sharded run by reassembling meta + sample shards."""
        meta_path = self._shard_meta_path(run_id)
        if not meta_path.exists():
            return None

        try:
            with open(meta_path) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to read shard meta %s: %s", meta_path, exc)
            return None

        # Reassemble prompt_results from all sample shard files
        data["prompt_results"] = []
        shard_dir = self._shard_dir(run_id)
        for shard_file in sorted(shard_dir.glob("*.json")):
            if shard_file.name == _META_FILENAME:
                continue
            try:
                with open(shard_file) as f:
                    sample_data = json.load(f)
                if isinstance(sample_data, list):
                    data["prompt_results"].extend(sample_data)
                elif isinstance(sample_data, dict):
                    # Single prompt_result dict
                    data["prompt_results"].append(sample_data)
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning(
                    "Failed to read shard %s: %s", shard_file, exc,
                )
                continue

        return EvalRun(**data)

    def _save_sharded(self, run: EvalRun) -> Path:
        """Save an evaluation run in sharded layout.

        Layout:
            results/{run_id}/meta.json        – everything except prompt_results
            results/{run_id}/{sample_id}.json – list of PromptResult dicts
        """
        shard_dir = self._shard_dir(run.run_id)
        shard_dir.mkdir(parents=True, exist_ok=True)

        # 1. Meta: full run data minus prompt_results
        meta = run.model_dump()
        meta.pop("prompt_results", None)
        meta_path = self._shard_meta_path(run.run_id)
        atomic_write_json(meta_path, meta, indent=2, ensure_ascii=False)
        logger.info("Saved shard meta to %s", meta_path)

        # 2. Group prompt_results by sample_id
        samples: dict[str, list[dict]] = {}
        for pr in run.prompt_results:
            key = pr.sample_id or pr.prompt_id or "unknown"
            samples.setdefault(key, []).append(pr.model_dump())

        # 3. Write per-sample shard files
        for sample_id, pr_list in samples.items():
            shard_path = self._shard_sample_path(run.run_id, sample_id)
            atomic_write_json(shard_path, pr_list, indent=2, ensure_ascii=False)
            logger.info(
                "Saved shard %s (%d prompt_result(s))", shard_path, len(pr_list),
            )

        return shard_dir

    # ------------------------------------------------------------------
    # Public API (backward compatible)
    # ------------------------------------------------------------------

    def save(self, run: EvalRun, *, sharded: bool = False) -> Path:
        """已弃用：数据源统一为 workspace，不再写入 results/ 目录。

        保留方法签名以维持向后兼容，但不再建议调用。
        新代码应使用 save_v2() 写入 workspace 目录。

        Args:
            run: The evaluation run to persist.
            sharded: When ``True``, store results in a per-sample sharded
                layout under ``results/{run_id}/``. When ``False`` (default),
                use the original flat layout ``results/{run_id}.json``.

        Returns:
            Path to the created file (flat) or shard directory (sharded).
        """
        warnings.warn(
            "ResultStore.save() is deprecated; use workspace APIs instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        if sharded:
            return self._save_sharded(run)

        self.results_dir.mkdir(parents=True, exist_ok=True)
        result_file = self.results_dir / f"{run.run_id}.json"

        atomic_write_json(result_file, run.model_dump(), indent=2, ensure_ascii=False)

        logger.info(f"Saved evaluation run to {result_file}")
        return result_file

    def load(self, run_id: str) -> EvalRun | None:
        """已弃用：数据源统一为 workspace，不再从 results/ 目录加载。

        保留方法签名以维持向后兼容。
        新代码应直接从 workspace 的 run_data.json 读取。

        Tries the sharded layout first, then falls back to the flat layout
        for backward compatibility.
        """
        warnings.warn(
            "ResultStore.load() is deprecated; use workspace APIs to read data.",
            DeprecationWarning,
            stacklevel=2,
        )
        # Try sharded layout first
        if self._is_sharded(run_id):
            result = self._load_sharded(run_id)
            if result is not None:
                return result

        # Fall back to flat layout
        result_file = self.results_dir / f"{run_id}.json"
        if not result_file.exists():
            logger.warning(f"Run not found: {run_id}")
            return None

        with open(result_file) as f:
            data = json.load(f)

        return EvalRun(**data)

    def list_runs(self) -> list[dict]:
        """已弃用：数据源统一为 workspace，不再从 results/ 目录列举。

        保留方法签名以维持向后兼容。
        新代码应扫描 workspace 目录下的 run_data.json。

        Discovers both flat and sharded runs.
        """
        warnings.warn(
            "ResultStore.list_runs() is deprecated; scan ~/eval_app_factory/ workspaces directly.",
            DeprecationWarning,
            stacklevel=2,
        )
        results: list[dict] = []
        if not self.results_dir.exists():
            return results

        seen_ids: set[str] = set()

        # 1. Discover sharded runs (directories containing meta.json)
        for entry in sorted(self.results_dir.iterdir(), reverse=True):
            if entry.is_dir():
                meta_path = entry / _META_FILENAME
                if not meta_path.exists():
                    continue
                try:
                    with open(meta_path) as f:
                        data = json.load(f)
                    run_id = data.get("run_id", entry.name)
                    results.append({
                        "run_id": run_id,
                        "generator_name": data.get("generator_name", ""),
                        "run_type": data.get("run_type", "prompt"),
                        "timestamp": data.get("timestamp", ""),
                        "total_prompts": data.get("summary", {}).get("total_prompts", 0),
                        "overall_pass_rate": data.get("summary", {}).get("overall_pass_rate", 0),
                        "storage": "sharded",
                    })
                    seen_ids.add(run_id)
                except (json.JSONDecodeError, KeyError, OSError):
                    continue

        # 2. Discover flat runs (*.json files)
        for json_file in sorted(self.results_dir.glob("*.json"), reverse=True):
            try:
                with open(json_file) as f:
                    data = json.load(f)
                run_id = data.get("run_id", json_file.stem)
                if run_id in seen_ids:
                    continue  # already discovered as sharded
                results.append({
                    "run_id": run_id,
                    "generator_name": data.get("generator_name", ""),
                    "run_type": data.get("run_type", "prompt"),
                    "timestamp": data.get("timestamp", ""),
                    "total_prompts": data.get("summary", {}).get("total_prompts", 0),
                    "overall_pass_rate": data.get("summary", {}).get("overall_pass_rate", 0),
                    "storage": "flat",
                })
            except (json.JSONDecodeError, KeyError):
                continue

        # Sort by timestamp descending (most recent first)
        results.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
        return results

    def get_latest(self) -> EvalRun | None:
        """已弃用：数据源统一为 workspace，不再从 results/ 目录获取最新记录。

        保留方法签名以维持向后兼容。
        """
        warnings.warn(
            "ResultStore.get_latest() is deprecated; locate the latest workspace by mtime.",
            DeprecationWarning,
            stacklevel=2,
        )
        runs = self.list_runs()
        if not runs:
            return None
        return self.load(runs[0]["run_id"])

    # ------------------------------------------------------------------
    # V2 output directory: save report_data.json + run data
    # ------------------------------------------------------------------

    def save_v2(
        self,
        run: EvalRun,
        *,
        output_dir: Path | None = None,
        base_dir: Path | None = None,
        dataset_version: str = "v1",
        eval_version: str = "",
    ) -> Path:
        """确保输出目录存在并返回其路径。

        run_data.json 和 report_data.json 已弃用，不再写入。
        新格式（各样本 scores.json + report/scores_summary.json）已完全替代。

        Args:
            output_dir: If provided, use this existing workspace directory
                       instead of creating a new one.
            base_dir: Base directory for creating new output dirs when
                     output_dir is None. Defaults to ~/eval_app_factory.
            dataset_version: Dataset version string for directory naming.
            eval_version: Evaluation version string for directory naming.

        Returns:
            Path to the created or reused output directory.
        """
        if output_dir is not None:
            # Reuse existing workspace directory created by CLI
            output_dir.mkdir(parents=True, exist_ok=True)
        else:
            # Create new directory (backward compatible)
            base = base_dir or Path.home() / "eval_app_factory"

            platforms = sorted({pr.platform for pr in run.prompt_results})
            platform_str = "-".join(platforms) if platforms else "unknown"
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")

            dir_name = (
                f"{run.generator_name}_{platform_str}"
                f"_{dataset_version}_{ts}"
            )
            output_dir = base / dir_name
            output_dir.mkdir(parents=True, exist_ok=True)

        return output_dir

    # ------------------------------------------------------------------
    # V2 output directory: export e2e test reports (report.html + bundle)
    # ------------------------------------------------------------------

    def export_e2e_reports(
        self,
        run: EvalRun,
        output_dir: Path,
        *,
        subdir: str = "e2e_reports",
        copy_bundle: bool = True,
        only_pairs: set[tuple[str, str]] | None = None,
    ) -> list[Path]:
        """Export e2e test reports into per-sample directories.

        For every ``TestCaseResult`` with a non-empty ``report_path`` that
        points to an existing file on disk, the report is exported under
        ``output_dir/<item_token>/<subdir>/`` with a recognisable name
        composed of the platform and test case id.

        **New behaviour**: if the report already exists under the sample's
        ``.test_intermediates/ai-ui-test/`` directory (written directly by
        Midscene when the evaluator uses ``workspace/{sample_id}/e2e_reports/``
        as ``report_dir``), the directory is *moved* (renamed) to the final
        location instead of being copied, saving disk I/O.

        **Backward compatibility**: when the source path is an external
        location (e.g. the snapshot cache under ``~/.cache/evalapp/``),
        it is copied as before.

        Args:
            run: The evaluation run whose prompt results will be scanned.
            output_dir: The V2 evaluation output directory.
            subdir: Sub-folder under *output_dir/<item_token>/* to hold
                the exported reports. Defaults to ``e2e_reports``.
            copy_bundle: When ``True`` (default) the entire parent folder
                of ``report.html`` is copied *only if* that folder looks
                like a per-case bundle. Shared report directories always
                fall back to single-file copy. When ``False`` only the
                HTML file itself is ever copied.
            only_pairs: When provided, only clean up and export reports
                for the specified ``(item_token, platform_token)`` pairs.
                Other existing reports in the target directory are left
                untouched.  This is useful for retest scenarios where only
                a subset of samples have fresh report_path values.
                When ``None`` (default), all prompt results are processed
                as before.

        Returns:
            The list of exported destination paths (files or directories).
        """
        exported: list[Path] = []

        # ------------------------------------------------------------------
        # Pre-compute per-sample platform tokens for stale cleanup.
        # ------------------------------------------------------------------
        sample_platforms: dict[str, set[str]] = {}  # item_token -> platform_tokens
        for pr in run.prompt_results:
            item_token = _sanitise_name(pr.sample_id or pr.prompt_id, "item")
            platform_token = _sanitise_name(pr.platform, "unknown")
            pair = (item_token, platform_token)
            if only_pairs is None or pair in only_pairs:
                sample_platforms.setdefault(item_token, set()).add(platform_token)

        # ------------------------------------------------------------------
        # Clean up stale e2e reports in per-sample directories.
        # Reports are now stored under output_dir/{item_token}/e2e_reports/
        # with names like {platform}_{tc}_{ts}, so we match on
        # {platform}_ prefix instead of the old {item}_{platform}_ prefix.
        # ------------------------------------------------------------------
        stale_removed = 0
        for item_token, platform_tokens in sample_platforms.items():
            sample_target = output_dir / item_token / subdir
            if not sample_target.is_dir():
                continue
            for entry in list(sample_target.iterdir()):
                if entry.name.startswith("."):
                    continue  # skip .test_intermediates etc.
                name = entry.name
                for platform_token in platform_tokens:
                    prefix = f"{platform_token}_"
                    stale_pfx = f"STALE_{platform_token}_"
                    if name.startswith(prefix) or name.startswith(stale_pfx):
                        try:
                            if entry.is_dir():
                                shutil.rmtree(entry)
                            else:
                                entry.unlink()
                        except OSError as exc:
                            logger.warning(
                                "Failed to remove old e2e report %s: %s",
                                entry, exc,
                            )
                        else:
                            stale_removed += 1
                        break  # matched one platform already
        if stale_removed:
            logger.info(
                "Cleaned up %d old e2e report(s) across %d sample(s)",
                stale_removed, len(sample_platforms),
            )

        # ------------------------------------------------------------------
        # Export each test result, preferring move from .test_intermediates
        # over copy from snapshot cache.
        # ------------------------------------------------------------------
        for pr in run.prompt_results:
            item_token = _sanitise_name(pr.sample_id or pr.prompt_id, "item")
            platform_token = _sanitise_name(pr.platform, "unknown")
            pair = (item_token, platform_token)
            if only_pairs is not None and pair not in only_pairs:
                continue

            # Per-sample target: output_dir/{item_token}/e2e_reports/
            sample_target = output_dir / item_token / subdir

            # Scan .test_intermediates/ai-ui-test/ for report directories
            # that Midscene wrote directly under the sample's e2e_reports.
            intermediates_root = sample_target / ".test_intermediates" / "ai-ui-test"
            intermediates_dirs: list[Path] = []
            if intermediates_root.is_dir():
                intermediates_dirs = sorted(
                    [d for d in intermediates_root.iterdir() if d.is_dir()],
                    key=lambda d: d.name,
                )

            first_exported_for_pr: Path | None = None

            for tr in pr.test_results:
                raw_path = (tr.report_path or "").strip()
                if not raw_path:
                    # report_path 为空时，尝试在 e2e_reports 目录下发现对应报告
                    tc_id_for_discover = (tr.test_case_id or "").strip()
                    discovered_src: Path | None = None
                    if tc_id_for_discover:
                        e2e_dir = output_dir / item_token / subdir
                        # 策略 a：查找匹配 *_{tc_id}_* 模式的独立目录
                        if e2e_dir.is_dir():
                            matched_dirs = [
                                d for d in e2e_dir.iterdir()
                                if d.is_dir()
                                and not d.name.startswith(".")
                                and f"_{tc_id_for_discover}_" in d.name
                            ]
                            if matched_dirs:
                                # 取最新的目录（按名称排序）
                                best_dir = sorted(matched_dirs, key=lambda d: d.name)[-1]
                                # 在目录内查找 playwright-*.html
                                pw_files = sorted(best_dir.glob("playwright-*.html"))
                                if pw_files:
                                    discovered_src = pw_files[-1]
                                else:
                                    # 尝试 report.html
                                    rp = best_dir / "report.html"
                                    if rp.exists():
                                        discovered_src = rp
                        # 策略 b（fallback）：当该 sample 只有一个未匹配的 TC 时
                        # 使用 midscene_run/report/playwright-*.html 作为通用回退
                        if discovered_src is None and e2e_dir.is_dir():
                            # 统计当前 pr 中有多少 TC 的 report_path 也为空
                            empty_report_tcs = [
                                t for t in pr.test_results
                                if not (t.report_path or "").strip()
                            ]
                            if len(empty_report_tcs) == 1:
                                midscene_report_dir = e2e_dir / "midscene_run" / "report"
                                if midscene_report_dir.is_dir():
                                    pw_files = sorted(midscene_report_dir.glob("playwright-*.html"))
                                    if pw_files:
                                        discovered_src = pw_files[-1]
                    if discovered_src is None or not discovered_src.exists():
                        continue
                    # 发现了报告文件，更新 raw_path 并继续正常的导出流程
                    raw_path = str(discovered_src)
                    logger.info(
                        "Discovered e2e report for empty report_path "
                        "(sample=%s tc=%s): %s",
                        item_token, tr.test_case_id, raw_path,
                    )

                src = Path(raw_path).expanduser()
                src_exists = src.exists()
                if not src_exists:
                    logger.warning(
                        "E2E report missing on disk, skip: %s "
                        "(sample=%s platform=%s tc=%s)",
                        raw_path, item_token, platform_token, tr.test_case_id,
                    )

                sample_target.mkdir(parents=True, exist_ok=True)
                tc_token = _sanitise_name(tr.test_case_id, "tc")

                # Timestamp suffix: prefer the report's generation time
                # captured at snapshot, fall back to test start time,
                # fall back to the file's current mtime.
                ts_source = tr.report_generated_at or tr.report_started_at
                if not ts_source and src_exists:
                    try:
                        ts_source = src.stat().st_mtime
                    except OSError:
                        ts_source = 0.0
                ts_suffix = (
                    datetime.fromtimestamp(ts_source).strftime("%Y%m%d_%H%M%S")
                    if ts_source
                    else "unknown"
                )

                # Stale check: if the file predates the declared test
                # start, prefix the export with ``STALE_`` so reviewers
                # can see there was a potential mismatch.
                stale = False
                if tr.report_started_at and tr.report_generated_at:
                    if tr.report_generated_at + 1.0 < tr.report_started_at:
                        stale = True
                stale_prefix = "STALE_" if stale else ""
                # Name format: {platform}_{tc}_{ts} (item_token is
                # now implicit in the directory path).
                base_name = (
                    f"{stale_prefix}{platform_token}_"
                    f"{tc_token}_{ts_suffix}"
                )
                if stale:
                    logger.warning(
                        "Exporting stale report for %s/%s/%s "
                        "(generated_at=%.0f < started_at=%.0f)",
                        item_token, platform_token, tc_token,
                        tr.report_generated_at, tr.report_started_at,
                    )

                # Try to find a matching .test_intermediates directory
                # by comparing report mtime with report_generated_at.
                # Look for report.html first, then playwright-*.html.
                intermediate_src = None
                if tr.report_generated_at and intermediates_dirs:
                    best_dir = None
                    best_diff = float("inf")
                    for idir in intermediates_dirs:
                        report_html = idir / "report.html"
                        if report_html.exists():
                            try:
                                mtime = report_html.stat().st_mtime
                            except OSError:
                                continue
                        else:
                            # Fallback to playwright-*.html inside the dir
                            pw_files = sorted(idir.glob("playwright-*.html"))
                            if not pw_files:
                                continue
                            try:
                                mtime = pw_files[-1].stat().st_mtime
                            except OSError:
                                continue
                        diff = abs(mtime - tr.report_generated_at)
                        if diff < best_diff and diff < 5.0:
                            best_diff = diff
                            best_dir = idir

                    if best_dir is not None:
                        intermediate_src = best_dir
                        intermediates_dirs.remove(best_dir)  # consume

                try:
                    if intermediate_src is not None:
                        # Report is already in .test_intermediates/ under
                        # the sample's e2e_reports: move (rename) instead
                        # of copying, saving disk I/O.
                        dest = self._unique_path(sample_target / base_name)
                        shutil.move(str(intermediate_src), str(dest))
                        logger.info(
                            "Moved e2e report from .test_intermediates: "
                            "%s -> %s",
                            intermediate_src, dest,
                        )
                    elif src_exists:
                        # Backward compat: copy from snapshot cache or
                        # other external location.
                        if src.is_dir():
                            dest = self._unique_path(sample_target / base_name)
                            shutil.copytree(src, dest)
                        elif (
                            copy_bundle
                            and src.is_file()
                            and src.parent.is_dir()
                            and not _is_shared_report_dir(src.parent)
                        ):
                            dest = self._unique_path(sample_target / base_name)
                            shutil.copytree(src.parent, dest)
                        else:
                            suffix = src.suffix or ".html"
                            dest = self._unique_path(
                                sample_target / f"{base_name}{suffix}"
                            )
                            shutil.copy2(src, dest)
                        logger.info(
                            "Copied e2e report: %s -> %s", src, dest,
                        )
                    else:
                        continue

                    exported.append(dest)

                    # Stale exports stay on disk (STALE_ prefix) for
                    # manual review only: never register them as this
                    # case's official report, so the frontend will not
                    # render a "查看详细报告" button pointing at a
                    # previous case's report.
                    if stale:
                        tr.report_path = ""
                        continue

                    if first_exported_for_pr is None:
                        first_exported_for_pr = dest

                    # Update tr.report_path to the exported relative path
                    # so the HTML report can link to it via the API.
                    try:
                        rel_dest = dest.relative_to(output_dir)
                        # If dest is a directory, point to the actual HTML inside
                        if dest.is_dir():
                            report_html = dest / "report.html"
                            if report_html.exists():
                                rel_dest = report_html.relative_to(output_dir)
                            else:
                                # Fallback: find playwright-*.html inside
                                playwright_files = sorted(dest.glob("playwright-*.html"))
                                if playwright_files:
                                    rel_dest = playwright_files[-1].relative_to(output_dir)
                        tr.report_path = str(rel_dest)
                    except ValueError:
                        tr.report_path = str(dest)
                except OSError as exc:
                    logger.warning(
                        "Failed to export e2e report for %s/%s/%s: %s",
                        item_token, platform_token, tc_token, exc,
                    )

            # Back-fill e2e_report_path so the HTML report can link to it
            if first_exported_for_pr and not pr.e2e_report_path:
                try:
                    pr.e2e_report_path = str(
                        first_exported_for_pr.relative_to(output_dir)
                    )
                except ValueError:
                    pr.e2e_report_path = str(first_exported_for_pr)

        # ------------------------------------------------------------------
        # Clean up empty .test_intermediates directories left after moves.
        # ------------------------------------------------------------------
        for item_token in sample_platforms:
            intermediates = output_dir / item_token / subdir / ".test_intermediates"
            if intermediates.exists():
                try:
                    has_files = any(
                        f.is_file() for f in intermediates.rglob("*")
                    )
                    if not has_files:
                        shutil.rmtree(intermediates)
                        logger.info(
                            "Cleaned up empty .test_intermediates for %s",
                            item_token,
                        )
                except OSError:
                    pass

        if exported:
            logger.info(
                "Exported %d e2e report(s)", len(exported),
            )
        return exported

    def export_stability_logs(
        self,
        run: EvalRun,
        output_dir: Path,
        *,
        subdir: str = "stability_logs",
    ) -> list[Path]:
        """Export device logs and stability data for each sample.

        Creates structured files under:
        - 多 Expo 模式: output_dir/<sample_id>/stability_logs/<platform>/
        - 单平台模式: output_dir/<sample_id>/stability_logs/<generator>/

        每个目录下包含:
        - device.log: Raw device log (Android logcat / iOS os_log)
        - crash_anr_events.json: Structured crash/ANR events

        Args:
            run: The evaluation run whose prompt results will be scanned.
            output_dir: The V2 evaluation output directory.
            subdir: Sub-folder name under each sample directory.

        Returns:
            The list of exported destination paths.
        """
        from ...workspace.paths import is_expo_platform, is_multi_expo_workspace

        exported: list[Path] = []

        for pr in run.prompt_results:
            # 检查是否有稳定性数据
            if not pr.result_data or not pr.result_data.stability_metrics:
                continue

            item_token = _sanitise_name(pr.sample_id or pr.prompt_id, "item")

            # 多 Expo 模式：按 platform 隔离；否则按 generator 隔离（向后兼容）
            generator_token = _sanitise_name(pr.generator_name, "unknown")
            multi_expo = is_multi_expo_workspace(output_dir)
            if multi_expo and is_expo_platform(pr.platform):
                subdir_token = _sanitise_name(pr.platform, "unknown")
                dest_dir = Path(output_dir) / item_token / subdir / subdir_token
            else:
                dest_dir = Path(output_dir) / item_token / subdir / generator_token
            dest_dir.mkdir(parents=True, exist_ok=True)

            stability = pr.result_data.stability_metrics

            # 1. 保存结构化事件
            events_data = {
                'platform': pr.platform,
                'sample_id': pr.sample_id or pr.prompt_id,
                'crash_count': stability.crash_count,
                'anr_count': stability.anr_count,
                'total_test_runs': stability.total_test_runs,
                'crash_rate': stability.crash_rate,
                'anr_rate': stability.anr_rate,
                'crash_free': stability.crash_free,
                'stability_score': stability.score,
                'white_screen_count': getattr(stability, 'white_screen_count', 0),
                'crash_events': [e.model_dump() for e in stability.crash_events],
                'anr_events': [e.model_dump() for e in stability.anr_events],
            }
            events_file = dest_dir / 'crash_anr_events.json'
            events_file.write_text(
                json.dumps(events_data, indent=2, ensure_ascii=False),
                encoding='utf-8'
            )
            exported.append(events_file)

            # 2. 复制原始日志文件(如果存在)
            # 原始日志在各测试用例目录下: {sample_id}/e2e_reports/{platform}_{tc_id}_{timestamp}/device.log
            sample_e2e_dir = Path(output_dir) / item_token / 'e2e_reports'
            if sample_e2e_dir.exists():
                # 收集所有 device.log 合并到 stability_logs 目录
                all_device_logs = list(sample_e2e_dir.rglob('device.log'))
                if len(all_device_logs) == 1:
                    # 只有一个日志直接复制
                    dest_log = dest_dir / 'device.log'
                    shutil.copy2(all_device_logs[0], dest_log)
                    exported.append(dest_log)
                elif len(all_device_logs) > 1:
                    # 多个日志合并为一个（按时间顺序追加）
                    dest_log = dest_dir / 'device.log'
                    with open(dest_log, 'w', encoding='utf-8') as out:
                        for log_file in sorted(all_device_logs):
                            try:
                                content = log_file.read_text(encoding='utf-8')
                                out.write(f"--- {log_file.parent.name} ---\n")
                                out.write(content)
                                if not content.endswith('\n'):
                                    out.write('\n')
                            except Exception:
                                pass
                    exported.append(dest_log)

            if any(dest_dir.iterdir()):
                log_label = subdir_token if (multi_expo and is_expo_platform(pr.platform)) else generator_token
                logger.info(
                    "Exported stability logs for %s/%s to %s",
                    log_label, item_token, dest_dir,
                )

        if exported:
            logger.info(
                "Exported %d stability log file(s)",
                len(exported),
            )
        return exported

    @staticmethod
    def _unique_path(candidate: Path) -> Path:
        """Return a non-conflicting path by appending ``_N`` if needed."""
        if not candidate.exists():
            return candidate
        stem, suffix = candidate.stem, candidate.suffix
        parent = candidate.parent
        for idx in range(1, 1000):
            alt = parent / f"{stem}_{idx}{suffix}"
            if not alt.exists():
                return alt
        return candidate

