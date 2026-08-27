"""Report data models for V2 evaluation report output.

Contains ReportMeta, ReportSampleResult, ReportData, and the
build_report_data() function for constructing report data from an EvalRun.
"""

from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, Field

from .execution import (
    EvalRun,
    _is_status_skipped,
    _is_status_success,
)
from .summary import EvalSummary


class ReportMeta(BaseModel):
    """Metadata for the V2 evaluation report."""

    eval_version: str = "2.0"
    dataset_version: str = ""
    generator: str = ""
    platform: str | list[str] = ""  # 单平台为字符串，多平台为数组
    complexity: str = ""
    sample_count: int = 0
    run_id: str = ""
    start_time: str = ""  # 评测开始时间
    end_time: str = ""    # 报告生成时间
    total_duration_ms: int = 0  # 总耗时（毫秒）


class ReportSampleResult(BaseModel):
    """Per-sample result entry for the V2 report."""

    sample_id: str = ""
    sample_title: str = ""  # 新增: 样本中文标题
    platform: str = ""
    complexity: str = ""
    top_category: str = ""  # 新增: TOP应用分类
    generation_success: bool = False
    install_success: bool = False
    launch_success: bool = False
    # 新顶层指标
    success_rate_score: float = 0.0
    quality_score: float = 0.0
    experience_score: float = 0.0
    duration_ms: int = 0
    # 子指标详情
    stability_score: float = 0.0
    functionality_score: float = 0.0
    error_message: str = ""
    is_deliverable: bool = False  # 是否可交付
    e2e_report_path: str = ""  # E2E测试报告路径
    # 指标原因
    success_rate_reason: str = ""  # 成功率原因
    usecase_reason: str = ""  # 用例完整性原因
    stability_reason: str = ""  # 稳定性原因
    duration_reason: str = ""  # 耗时原因

    # 包大小详情
    package_size_bytes: int = 0
    package_size_reason: str = ""

    # Token 详情
    token_input: int = 0
    token_output: int = 0
    token_total: int = 0
    # 稳定性详情(新增)
    crash_count: int = 0
    anr_count: int = 0
    white_screen_count: int = 0
    has_stability_logs: bool = False  # 是否有日志可查看
    stability_log_path: str = ""  # 稳定性日志相对路径

    # 逐条E2E用例结果
    e2e_test_cases: list[dict] = Field(default_factory=list)  # 每条E2E用例的详细结果

    # 后端完整性相关字段
    requires_backend: bool = False  # 样本是否需要后端服务
    backend_completeness: float | None = None  # 后端完整性评分（100/0/None），None=不适用
    backend_completeness_reason: str = ""  # 后端完整性评分原因
    backend_requests: list[dict] = Field(default_factory=list)  # 后端 API 请求记录


class ReportData(BaseModel):
    """Top-level V2 report data structure (serialised as report_data.json)."""

    meta: ReportMeta = Field(default_factory=ReportMeta)
    summary: EvalSummary = Field(default_factory=EvalSummary)
    sample_results: list[ReportSampleResult] = Field(default_factory=list)
    top_level_summary: dict = Field(default_factory=dict)  # 顶层指标汇总
    cross_platform_comparison: dict = Field(default_factory=dict)  # 跨平台一致性对比


def _extract_backend_requests(pr) -> list:
    """从 PromptResult.test_results 提取后端 API 请求记录。"""
    backend_requests = []
    if not getattr(pr, 'requires_backend', False):
        return backend_requests
    for tr in getattr(pr, 'test_results', []) or []:
        verifications = getattr(tr, 'verifications', None)
        if verifications and isinstance(verifications, dict) and 'real_backend' in verifications:
            rb = verifications['real_backend']
            if isinstance(rb, dict) and rb.get('requests'):
                backend_requests.extend(rb['requests'])
    return backend_requests


def build_report_data(
    run: EvalRun,
    *,
    dataset_version: str = "",
    eval_version: str = "",
) -> ReportData:
    """Build a V2 ReportData from an EvalRun.

    Extracts structured, JSON-serialisable data suitable for
    ``report_data.json`` and the HTML report template.

    .. deprecated::
        report_data.json 写入已废弃，新格式请使用 scores_summary.json。
        此函数仍可用于内存中构建报告数据，但不应再触发 report_data.json 的磁盘写入。
    """
    import warnings
    warnings.warn(
        "build_report_data() 已废弃，report_data.json 写入将在 v3.0 移除。"
        "新格式请使用 scores_summary.json。",
        DeprecationWarning,
        stacklevel=2,
    )
    # Determine platform / complexity from prompt results
    platforms = sorted({pr.platform for pr in run.prompt_results})
    
    def _count_white_screen_from_cases(test_cases: list) -> tuple[int, list[str]]:
        """e2e_test_cases中从verifications读取白屏次数

        优先从 TestCaseResult.verifications.white_screen.detected 读取。
        如果 verifications 为 None（老数据兼容），白屏数计为 0。
        注意：跟随 validators.py 逻辑，跳过已通过的测试用例中的白屏检测（瞬时空白帧）。
        """
        count = 0
        evidence = []
        for tc in test_cases:
            verifications = tc.get('verifications')
            if verifications and "white_screen" in verifications:
                if verifications["white_screen"].get("detected", False):
                    # 跳过已通过测试用例中的白屏——瞬时加载空白帧，非真实白屏
                    if tc.get('passed', False):
                        continue
                    count += 1
                    evidence.append(tc.get('test_case_id', ''))

        return count, evidence
    complexities = sorted(
        {pr.sample_complexity for pr in run.prompt_results if pr.sample_complexity}
    )

    # Derive dataset version from sample_source directory name if not provided
    if not dataset_version and run.sample_source:
        m = re.search(r'eval_samples_(v\d+)', run.sample_source)
        if m:
            dataset_version = m.group(1)

    # 计算时间信息
    start_time = run.timestamp  # EvalRun创建时间即开始时间
    end_time = datetime.now().isoformat()  # 当前时间即结束时间
    
    # 计算总耗时
    start_dt = datetime.fromisoformat(start_time)
    end_dt = datetime.fromisoformat(end_time)
    total_duration_ms = int((end_dt - start_dt).total_seconds() * 1000)
    
    meta = ReportMeta(
        eval_version=eval_version,
        dataset_version=dataset_version,
        generator=run.generator_name,
        platform=", ".join(platforms),
        complexity=", ".join(complexities) if complexities else "mixed",
        sample_count=len(run.prompt_results),
        run_id=run.run_id,
        start_time=start_time,
        end_time=end_time,
        total_duration_ms=total_duration_ms,
    )

    sample_results: list[ReportSampleResult] = []
    for pr in run.prompt_results:
        rd = pr.result_data
        install_ok = rd is not None and (
            _is_status_skipped(rd.install_status) or _is_status_success(rd.install_status)
        )
        launch_ok = rd is not None and _is_status_success(rd.launch_status)
        
        # 使用新顶层指标
        success_rate_score = pr.success_rate.composite_score if pr.success_rate else 0.0
        quality_score = pr.quality.composite_score if pr.quality else 0.0
        experience_score = pr.experience.composite_score if pr.experience else 0.0
        duration_ms = pr.experience.end_to_end_duration_ms if pr.experience else 0
        
        # 加载用例中文名称和描述映射
        tc_name_map: dict[str, str] = {}
        tc_desc_map: dict[str, str] = {}
        try:
            from pathlib import Path
            import json as _json
            dataset_dir = Path(__file__).parent.parent.parent.parent / "dataset"
            _sample_id = pr.item_id
            _platform = pr.platform
            # Collect all category dirs including those under version subdirs
            _cat_dirs: list[Path] = []
            for entry in dataset_dir.iterdir():
                if not entry.is_dir():
                    continue
                # If entry contains sample directly, treat as category
                if (entry / _sample_id).is_dir():
                    _cat_dirs.append(entry)
                else:
                    # Treat as version dir, iterate its children
                    for sub in entry.iterdir():
                        if sub.is_dir():
                            _cat_dirs.append(sub)
            for cat_dir in _cat_dirs:
                tc_file = cat_dir / _sample_id / "test_cases" / f"test_cases_{_platform}.json"
                if tc_file.exists():
                    with open(tc_file, "r", encoding="utf-8") as f:
                        tc_data = _json.load(f)
                    for tc_def in tc_data.get("test_cases", []):
                        tc_id = tc_def.get("id")
                        if tc_id:
                            tc_name_map[tc_id] = tc_def.get("name", "")
                            tc_desc_map[tc_id] = tc_def.get("description", "")
                    break
        except Exception:
            pass
        
        sample_results.append(
            ReportSampleResult(
                sample_id=pr.item_id,
                sample_title=pr.sample_title,  # 新增
                platform=pr.platform,
                complexity=pr.sample_complexity,
                top_category=pr.sample_top_category,  # 新增
                generation_success=pr.generation_success,
                install_success=install_ok,
                launch_success=launch_ok,
                success_rate_score=success_rate_score,
                quality_score=quality_score,
                experience_score=experience_score,
                duration_ms=duration_ms,
                stability_score=(pr.quality.stability_score if pr.quality and pr.quality.stability_score is not None else 0.0),
                functionality_score=pr.quality.usecase_completeness if pr.quality else 0.0,
                is_deliverable=launch_ok and quality_score >= 70,  # 简单判定
                error_message=pr.error_message[:300] if pr.error_message else "",
                e2e_report_path=pr.e2e_report_path if pr.e2e_report_path else "",
                # 指标原因
                success_rate_reason=pr.success_rate.initial_generation_reason if pr.success_rate else "",
                usecase_reason=pr.quality.usecase_reason if pr.quality else "",
                stability_reason=pr.quality.stability_reason if pr.quality else "",
                duration_reason=pr.experience.duration_reason if pr.experience else "",
                # 包大小详情
                package_size_bytes=pr.experience.package_size_bytes if pr.experience else 0,
                package_size_reason=pr.experience.package_size_reason if pr.experience else "",
                # Token 详情
                token_input=pr.experience.token_input if pr.experience else 0,
                token_output=pr.experience.token_output if pr.experience else 0,
                token_total=pr.experience.token_total if pr.experience else 0,
                # 稳定性详情
                crash_count=pr.quality.crash_count if pr.quality else 0,
                anr_count=pr.quality.anr_count if pr.quality else 0,
                # 白屏次数：优先使用 pr.quality.white_screen_count（已从verifications产出）
                white_screen_count=getattr(pr.quality, 'white_screen_count', 0) if pr.quality else 0,
                has_stability_logs=bool(pr.result_data and pr.result_data.stability_metrics and pr.result_data.stability_metrics.total_test_runs > 0),
                stability_log_path=f"{pr.item_id}/stability_logs/{pr.generator_name}/" if (pr.result_data and pr.result_data.stability_metrics and pr.result_data.stability_metrics.total_test_runs > 0) else "",
                # 逐条E2E用例结果
                e2e_test_cases=[
                    {
                        "test_case_id": tc.test_case_id,
                        "test_case_name": tc_name_map.get(tc.test_case_id, ""),
                        "test_case_description": tc_desc_map.get(tc.test_case_id, ""),
                        "passed": tc.passed,
                        "status": tc.status or ("PASS" if tc.passed else "FAIL"),
                        "details": tc.details or "",
                        "report_path": tc.report_path or "",
                        "duration": tc.duration,
                    }
                    for tc in pr.test_results
                ],
                # 后端完整性字段
                requires_backend=getattr(pr, 'requires_backend', False),
                backend_completeness=pr.quality.backend_completeness if pr.quality else None,
                backend_completeness_reason=pr.quality.backend_completeness_reason if pr.quality else "",
                backend_requests=_extract_backend_requests(pr),
            )
        )
    
    # 构建完成后,对每个样本计算白屏次数(如果stability_metrics为空)
    for sr in sample_results:
        if sr.white_screen_count == 0 and sr.e2e_test_cases:
            ws_count, ws_evidence = _count_white_screen_from_cases(sr.e2e_test_cases)
            sr.white_screen_count = ws_count
    
    # 注意: 顶层指标汇总已在 EvalRun.compute_summary() 中通过 _compute_top_level_summary() 计算
    # 此处不再重复计算,直接使用 run.summary.top_level_summary
    # 这样可以确保数据一致性,避免两处计算逻辑不一致导致的问题

    return ReportData(
        meta=meta,
        summary=run.summary,
        sample_results=sample_results,
        top_level_summary=run.summary.top_level_summary or {},
    )
