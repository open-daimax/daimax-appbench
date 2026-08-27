"""样本级数据写入。

修复要点：
* 所有写入改为原子写入（写临时文件 + ``os.replace`` 重命名），避免大文件
  写入中途崩溃导致数据损坏（W-05）。
* ``write_evaluation`` 也对结果应用 ``round_scores``，统一与 ``write_scores``
  的精度策略，避免上游浮点抖动导致前端展示不一致（W-13）。``write_generation``
  仅记录生成元数据，不含分值，保持原状即可。
* ``write_sample_scores`` 提供逐样本评分持久化，每个样本×平台评测完成后
  立即落盘，避免后续汇总步骤报错时丢失已有评分数据。
* ``consolidate_sample_report`` 将散落在 generation.json / scores.json /
  evaluation.json / sample.yaml 中的数据合并写入 sample_report.json，使其
  成为该样本的自包含报告。下游只需读取一个文件即可获取全部评测信息。
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from ..utils.files import round_scores
from ..utils.logging import get_logger
from ._safe_io import atomic_write_json, file_lock

logger = get_logger(__name__)


def write_generation(workspace_dir: Path, sample_id: str, data: dict):
    """写入样本的 generation.json（原子写入）。"""
    workspace_dir = Path(workspace_dir)
    sample_dir = workspace_dir / sample_id
    sample_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(sample_dir / "generation.json", data)


def write_evaluation(workspace_dir: Path, sample_id: str, data: dict):
    """写入样本的 evaluation.json（原子写入 + 统一精度）。"""
    workspace_dir = Path(workspace_dir)
    sample_dir = workspace_dir / sample_id
    sample_dir.mkdir(parents=True, exist_ok=True)
    # evaluation 含子指标分值，统一调用 round_scores 与 scores.json 对齐精度
    data = round_scores(data)
    atomic_write_json(sample_dir / "evaluation.json", data)


def write_scores(workspace_dir: Path, sample_id: str, data: dict):
    """写入样本的 scores.json（增量合并，支持多平台并发写入）。

    多平台并行评测时，各平台会同时调用此函数写入自己的评分数据。
    使用 file_lock + 读-改-写模式确保各平台数据不互相覆盖：
    - 若 data 包含 platforms 字段，则增量合并（保留现有平台，追加/更新新平台）
    - 若 data 不含 platforms 字段（旧格式），直接覆盖写入（向后兼容）
    """
    workspace_dir = Path(workspace_dir)
    sample_dir = workspace_dir / sample_id
    sample_dir.mkdir(parents=True, exist_ok=True)

    target = sample_dir / "scores.json"
    lock_path = sample_dir / ".scores.lock"

    data = round_scores(data)

    # 如果 data 不含 platforms 字段，直接覆盖写入（向后兼容旧格式）
    new_platforms = data.get("platforms")
    if not isinstance(new_platforms, dict):
        atomic_write_json(target, data)
        return

    with file_lock(lock_path):
        existing: dict = {}
        if target.exists():
            try:
                existing = json.loads(target.read_text(encoding="utf-8")) or {}
            except json.JSONDecodeError as exc:
                logger.warning(
                    "scores.json corrupted at %s: %s; resetting to empty",
                    target, exc,
                )
                existing = {}
            except OSError as exc:
                logger.error(
                    "failed to read scores.json at %s: %s", target, exc,
                )
                raise
        if not isinstance(existing, dict):
            existing = {}

        # 合并 platforms：保留现有各平台数据，追加/更新新平台
        existing_platforms = existing.get("platforms")
        if not isinstance(existing_platforms, dict):
            existing_platforms = {}
        existing_platforms.update(new_platforms)

        # 合并顶层字段（new data 的 sample_id 等元数据优先）
        merged = {**existing, **data}
        merged["platforms"] = existing_platforms

        atomic_write_json(target, merged)


def write_runtime_errors(
    workspace_dir: Path,
    sample_id: str,
    platform: str,
    errors: list[dict],
) -> None:
    """写入样本的 runtime_errors.json（增量合并，支持多平台并发写入）。

    严格仿照 :func:`write_scores` 的 file_lock + 读-改-写 + atomic_write_json 模式。
    锁文件为 ``.runtime_errors.lock``，仅更新 ``platforms.{platform}`` 并重算 summary。

    跨仓库契约 schema::

        {
          "schema_version": "1.0",
          "platforms": {
            "expo_web": {
              "errors": [...],
              "summary": {"page_not_found_count": 1, ...}
            }
          }
        }

    每平台 errors 上限 50 条，超出截断并置 ``"truncated": true``。
    errors 为空时不写文件、不改现有文件。文件不存在即无错误。

    Args:
        workspace_dir: 工作区根目录。
        sample_id: 样本 ID。
        platform: 评测平台（如 expo_web）。
        errors: 错误条目列表（由 :func:`extract_runtime_errors` 生成）。
    """
    from ..evaluation.runner.runtime_errors import compute_runtime_errors_summary

    # errors 为空时不写文件、不改现有文件
    if not errors:
        return

    workspace_dir = Path(workspace_dir)
    sample_dir = workspace_dir / sample_id
    sample_dir.mkdir(parents=True, exist_ok=True)

    target = sample_dir / "runtime_errors.json"
    lock_path = sample_dir / ".runtime_errors.lock"

    # 每平台 errors 上限 50 条，超出截断
    max_errors = 50
    truncated = len(errors) > max_errors
    errors_to_write = errors[:max_errors]

    summary = compute_runtime_errors_summary(errors_to_write, truncated)
    platform_entry = {
        "errors": errors_to_write,
        "summary": summary,
    }

    with file_lock(lock_path):
        existing: dict = {}
        if target.exists():
            try:
                existing = json.loads(target.read_text(encoding="utf-8")) or {}
            except json.JSONDecodeError as exc:
                logger.warning(
                    "runtime_errors.json corrupted at %s: %s; resetting to empty",
                    target, exc,
                )
                existing = {}
            except OSError as exc:
                logger.error(
                    "failed to read runtime_errors.json at %s: %s", target, exc,
                )
                raise
        if not isinstance(existing, dict):
            existing = {}

        # 顶层 schema_version 始终为 "1.0"
        existing["schema_version"] = "1.0"

        existing_platforms = existing.get("platforms")
        if not isinstance(existing_platforms, dict):
            existing_platforms = {}
        existing_platforms[platform] = platform_entry
        existing["platforms"] = existing_platforms

        atomic_write_json(target, existing)


def read_generation(workspace_dir: Path, sample_id: str) -> dict | None:
    """读取样本的 generation.json"""
    workspace_dir = Path(workspace_dir)
    path = workspace_dir / sample_id / "generation.json"
    if path.exists():
        return json.loads(path.read_text())
    return None


def read_evaluation(workspace_dir: Path, sample_id: str) -> dict | None:
    """读取样本的 evaluation.json"""
    workspace_dir = Path(workspace_dir)
    path = workspace_dir / sample_id / "evaluation.json"
    if path.exists():
        return json.loads(path.read_text())
    return None


def read_scores(workspace_dir: Path, sample_id: str) -> dict | None:
    """读取样本的 scores.json"""
    workspace_dir = Path(workspace_dir)
    path = workspace_dir / sample_id / "scores.json"
    if path.exists():
        return json.loads(path.read_text())
    return None


def _sample_scores_path(workspace_dir: Path, sample_id: str) -> Path:
    return Path(workspace_dir) / sample_id / "sample_scores.json"


def write_sample_scores(
    workspace_dir: Path,
    sample_id: str,
    platform: str,
    prompt_result: dict,
    scores: dict | None = None,
) -> None:
    """逐样本×平台持久化评分数据到 ``{workspace}/{sample_id}/sample_scores.json``。

    采用 file_lock 保护读改写流程，支持同一样本下多平台增量合并；
    底层调用 ``atomic_write_json`` 确保崩溃安全。

    Args:
        workspace_dir: 工作区根目录。
        sample_id: 样本 ID。
        platform: 评测平台（如 android/ios/miniprogram）。
        prompt_result: ``PromptResult.model_dump()`` 的结果。
        scores: 可选的精简评分摘要（如 composite_score、pass_count）。
    """
    workspace_dir = Path(workspace_dir)
    sample_dir = workspace_dir / sample_id
    sample_dir.mkdir(parents=True, exist_ok=True)
    target = sample_dir / "sample_scores.json"
    lock_path = sample_dir / ".sample_scores.lock"

    now = datetime.now().isoformat(timespec="seconds")
    platform_entry: dict[str, Any] = {
        "platform": platform,
        "updated_at": now,
        "prompt_result": prompt_result,
    }
    if scores is not None:
        platform_entry["scores"] = scores

    with file_lock(lock_path):
        existing: dict[str, Any] = {}
        if target.exists():
            try:
                existing = json.loads(target.read_text(encoding="utf-8")) or {}
            except json.JSONDecodeError as exc:
                # JSON 损坏：记录 warning 并重置为默认值，避免静默丢失问题
                logger.warning(
                    "sample_scores.json corrupted at %s: %s; resetting to empty",
                    target, exc,
                )
                existing = {}
            except OSError as exc:
                # I/O 错误（权限/磁盘/设备异常）不能静默吞掉，记错后重新抛出
                logger.error(
                    "failed to read sample_scores.json at %s: %s", target, exc,
                )
                raise
        if not isinstance(existing, dict):
            existing = {}

        platforms = existing.get("platforms")
        if not isinstance(platforms, dict):
            platforms = {}
        platforms[platform] = platform_entry

        data = {
            "sample_id": sample_id,
            "updated_at": now,
            "platforms": platforms,
        }
        atomic_write_json(target, data)


def read_sample_scores(workspace_dir: Path, sample_id: str) -> dict | None:
    """读取样本的 sample_scores.json（不存在或损坏时返回 None）。"""
    path = _sample_scores_path(workspace_dir, sample_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def iter_sample_scores(workspace_dir: Path):
    """遍历工作区下所有 ``{sample_id}/sample_scores.json`` 内容。

    Yields:
        (sample_id, data) 元组。data 为反序列化后的 dict，损坏的文件会被跳过。
    """
    workspace_dir = Path(workspace_dir)
    if not workspace_dir.exists():
        return
    for sample_dir in workspace_dir.iterdir():
        if not sample_dir.is_dir():
            continue
        target = sample_dir / "sample_scores.json"
        if not target.exists():
            continue
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, dict):
            yield sample_dir.name, data


# ====================== 自包含报告合并 ======================


def _find_sample_yaml(sample_id: str) -> Path | None:
    """在 dataset 目录下查找 sample_id 对应的 sample.yaml 文件。"""
    from ..utils.paths import get_project_root

    dataset_base = get_project_root() / "dataset"
    if not dataset_base.exists():
        return None
    for category_dir in dataset_base.iterdir():
        if not category_dir.is_dir():
            continue
        candidate = category_dir / sample_id / "sample.yaml"
        if candidate.exists():
            return candidate
    return None


def _load_sample_metadata(sample_id: str) -> dict[str, Any]:
    """从 sample.yaml 读取元数据（sample_title, complexity, top_category）。"""
    import yaml

    meta: dict[str, Any] = {}
    yaml_path = _find_sample_yaml(sample_id)
    if yaml_path is None:
        return meta
    try:
        with open(yaml_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if data.get("title"):
            meta["sample_title"] = data["title"]
        if data.get("complexity"):
            meta["complexity"] = data["complexity"]
        if data.get("top_category"):
            meta["top_category"] = data["top_category"]
        elif data.get("app_type"):
            meta["top_category"] = data["app_type"]
    except Exception:
        pass
    return meta


def consolidate_sample_report(workspace_dir: Path, sample_id: str) -> None:
    """将散落在不同文件中的数据合并写入 sample_report.json，使其成为自包含报告。

    合并来源：
    - 现有 sample_report.json / generation.json → 生成阶段数据
    - scores.json → 评分数据（success_rate_score, quality_score, aesthetics 等）
    - evaluation.json → E2E 测试结果（test_results, stability_metrics 等）
    - dataset sample.yaml → 元数据（sample_title, complexity, top_category）

    合并后的 sample_report.json 包含该样本的全部评测信息，下游只需读取
    一个文件即可获取完整数据。缺失字段设为 ``null``，保持向后兼容。

    Args:
        workspace_dir: 工作区根目录。
        sample_id: 样本 ID。
    """
    from ..utils.json_io import read_json as _read_json

    workspace_dir = Path(workspace_dir)
    sample_dir = workspace_dir / sample_id
    report_path = sample_dir / "sample_report.json"

    # --- 1. 以现有 sample_report.json / generation.json 为基础 ---
    report_data: dict[str, Any] = {}
    for candidate in (report_path, sample_dir / "generation.json"):
        if candidate.exists():
            try:
                report_data = _read_json(candidate) or {}
                if report_data:
                    break
            except Exception:
                report_data = {}

    report_data.setdefault("sample_id", sample_id)

    # --- 2. 合并 scores.json 中每个平台的评分数据 ---
    scores_path = sample_dir / "scores.json"
    if scores_path.exists():
        try:
            scores = _read_json(scores_path) or {}
            scores_platforms = scores.get("platforms", {})
            if isinstance(scores_platforms, dict) and scores_platforms:
                _ensure_platforms_dict(report_data)
                for plat, plat_scores in scores_platforms.items():
                    if not isinstance(plat_scores, dict):
                        continue
                    if plat not in report_data["platforms"]:
                        report_data["platforms"][plat] = {}
                    # 写入评分字段（scores.json 的值始终覆盖 sample_report.json 中的旧值）
                    for key in (
                        "success_rate_score", "quality_score", "experience_score",
                        "stability_score", "launch_screenshot",
                        "requires_backend", "backend_completeness",
                        "backend_completeness_reason", "backend_requests",
                        "aesthetics_score", "aesthetics_reason", "aesthetics_issues",
                        "aesthetics_dimensions", "aesthetics_rule_version",
                        "aesthetics_scored_frames",
                    ):
                        if key in plat_scores:
                            report_data["platforms"][plat][key] = plat_scores[key]
        except Exception as e:
            logger.warning("Failed to read scores.json for %s: %s", sample_id, e)

    # --- 3. 合并 evaluation.json 中每个平台的评测数据 ---
    eval_path = sample_dir / "evaluation.json"
    if eval_path.exists():
        try:
            eval_data = _read_json(eval_path) or {}
            eval_platforms = eval_data.get("platforms", {})
            if isinstance(eval_platforms, dict) and eval_platforms:
                _ensure_platforms_dict(report_data)
                for plat, plat_eval in eval_platforms.items():
                    if not isinstance(plat_eval, dict):
                        continue
                    if plat not in report_data["platforms"]:
                        report_data["platforms"][plat] = {}
                    plat_entry = report_data["platforms"][plat]

                    # 状态字段
                    for key in ("build_status", "install_status", "launch_status"):
                        if key in plat_eval and key not in plat_entry:
                            plat_entry[key] = plat_eval[key]

                    # stability_metrics → 扁平字段
                    stab = plat_eval.get("stability_metrics", {})
                    if isinstance(stab, dict):
                        plat_entry.setdefault("crash_count", stab.get("crash_count", 0))
                        plat_entry.setdefault("anr_count", stab.get("anr_count", 0))
                        plat_entry.setdefault("white_screen_count", stab.get("white_screen_count", 0))

                    # test_results → e2e_test_cases
                    test_results = plat_eval.get("test_results", [])
                    if test_results:
                        plat_entry["e2e_test_cases"] = test_results

                    # 派生字段
                    # 对于 h5 / miniprogram / expo_web 等平台，原生 build 和 install
                    # 步骤是预期跳过的（它们使用 npm build + 本地 serve），
                    # 不应将 skipped 等同于生成/安装失败。
                    build_st = plat_eval.get("build_status", "skipped")
                    install_st = plat_eval.get("install_status", "skipped")
                    launch_st = plat_eval.get("launch_status", "skipped")

                    _skip_native_build = plat in ("h5", "miniprogram", "expo_web")

                    if build_st == "success":
                        gen_success = True
                    elif build_st == "failed":
                        gen_success = False
                    elif _skip_native_build:
                        gen_success = True
                    else:
                        gen_success = False
                    plat_entry["generation_success"] = gen_success

                    if install_st == "success":
                        inst_success = True
                    elif install_st == "failed":
                        inst_success = False
                    elif _skip_native_build:
                        inst_success = True
                    else:
                        inst_success = False
                    plat_entry["install_success"] = inst_success

                    plat_entry["launch_success"] = launch_st not in ("failed", "skipped")
                    plat_entry["is_deliverable"] = (
                        plat_entry["generation_success"]
                        and plat_entry["install_success"]
                        and plat_entry["launch_success"]
                    )

                    # 检查 stability_logs 是否存在
                    stab_dir = sample_dir / "stability_logs"
                    if stab_dir.is_dir():
                        for gen_dir in stab_dir.iterdir():
                            crash_file = gen_dir / "crash_anr_events.json"
                            if crash_file.exists():
                                plat_entry.setdefault("has_stability_logs", True)
                                plat_entry.setdefault(
                                    "stability_log_path",
                                    str(crash_file.relative_to(sample_dir)),
                                )
                                break
                    plat_entry.setdefault("has_stability_logs", False)
                    plat_entry.setdefault("stability_log_path", None)
        except Exception as e:
            logger.warning("Failed to read evaluation.json for %s: %s", sample_id, e)

    # --- 4. 从 sample.yaml 获取元数据 ---
    yaml_meta = _load_sample_metadata(sample_id)
    for key in ("sample_title", "complexity", "top_category"):
        if key in yaml_meta and key not in report_data:
            report_data[key] = yaml_meta[key]

    # --- 5. 设置 evaluated_at ---
    report_data["evaluated_at"] = datetime.now().isoformat(timespec="seconds")

    # --- 6. 对尚无值的新字段填充 null（向后兼容） ---
    for key in ("sample_title", "complexity", "top_category", "error_message",
                "functionality_score", "success_rate_reason",
                "usecase_reason", "stability_reason",
                "duration_reason", "package_size_reason"):
        report_data.setdefault(key, None)

    # per-platform 缺失字段也填充 null
    for plat_entry in report_data.get("platforms", {}).values():
        if not isinstance(plat_entry, dict):
            continue
        for key in ("functionality_score", "error_message",
                    "success_rate_reason", "usecase_reason",
                    "stability_reason", "duration_reason",
                    "package_size_reason"):
            plat_entry.setdefault(key, None)

    # --- 7. 原子写入 ---
    sample_dir.mkdir(parents=True, exist_ok=True)
    report_data = round_scores(report_data)
    atomic_write_json(report_path, report_data)
    logger.debug("Consolidated sample_report.json for %s", sample_id)


def consolidate_all_sample_reports(workspace_dir: Path) -> None:
    """遍历工作区下所有样本目录，逐个合并生成自包含 sample_report.json。

    仅处理包含 generation.json / scores.json / evaluation.json 中至少一个的目录。
    """
    workspace_dir = Path(workspace_dir)
    if not workspace_dir.exists():
        return
    for sample_dir in sorted(workspace_dir.iterdir()):
        if not sample_dir.is_dir() or sample_dir.name.startswith("."):
            continue
        # 跳过已知非样本目录
        if sample_dir.name in ("e2e_reports", "stability_logs", "report",
                                "harness", "intermediate", "__pycache__"):
            continue
        # 至少含一个数据文件才处理
        has_data = any(
            (sample_dir / f).exists()
            for f in ("generation.json", "scores.json", "evaluation.json", "sample_report.json")
        )
        if has_data:
            try:
                consolidate_sample_report(workspace_dir, sample_dir.name)
            except Exception as e:
                logger.warning(
                    "Failed to consolidate sample_report.json for %s: %s",
                    sample_dir.name, e,
                )


def _ensure_platforms_dict(report_data: dict) -> None:
    """确保 report_data 中 'platforms' 键为 dict 类型。"""
    platforms = report_data.get("platforms")
    if not isinstance(platforms, dict):
        report_data["platforms"] = {}
