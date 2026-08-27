"""质量维度：用例完整性为基础分，稳定性/后端完整性按减法扣分。

公式: 功能完整性 = 用例完整性 - 稳定性扣分 - 后端完整性扣分
- 稳定性扣分 = (1 - stability_score/100) × 用例完整性 × QUALITY_STABILITY_DEDUCTION_RATIO
- 后端完整性扣分 = (1 - backend_completeness/100) × 用例完整性 × QUALITY_BACKEND_DEDUCTION_RATIO
- 缺失项不扣分，最低为0
"""

from __future__ import annotations

from ..models import QualityMetrics
from ..rules import (
    QUALITY_BACKEND_DEDUCTION_RATIO,
    QUALITY_STABILITY_DEDUCTION_RATIO,
    QUALITY_USECASE_MOSTLY_PASS_RATIO,
    QUALITY_USECASE_PARTIAL_PASS_RATIO,
    STABILITY_MINOR_ISSUE_SCORE,
    STABILITY_NOTABLE_ISSUE_SCORE,
)
from .backend import score_backend_completeness


def compute_quality(
    e2e_pass_rate: float,
    stability_score: float | None,
    e2e_pass_count: int = 0,
    e2e_total_count: int = 0,
    crash_count: int = 0,
    anr_count: int = 0,
    crash_free: bool = True,
    build_status: str = "unknown",
    install_status: str = "unknown",
    launch_status: str = "unknown",
    white_screen_count: int = 0,
    requires_backend: bool = False,
    real_backend_pass: bool | None = None,
    real_backend_pass_rate: float | None = None,
) -> QualityMetrics:
    """计算综合质量得分

    Args:
        e2e_pass_rate: E2E测试通过率 (0-1或0-100)
        stability_score: 稳定性得分 (0-100), None表示无数据
        e2e_pass_count: E2E通过数
        e2e_total_count: E2E总数
        crash_count: 崩溃次数
        anr_count: ANR次数
        crash_free: 是否无崩溃
        build_status: 构建状态 (success/failed/unknown)
        install_status: 安装状态 (success/failed/skipped/unknown)
        launch_status: 启动状态 (success/failed/unknown)
        white_screen_count: 白屏次数
        requires_backend: 样本是否需要后端服务
        real_backend_pass: 后端验证是否通过, None表示无real_backend数据
        real_backend_pass_rate: 后端验证通过率 (0.0-1.0), None表示无数据

    Returns:
        QualityMetrics with composite_score
    """
    # 归一化到0-100
    e2e_rate_100 = e2e_pass_rate * 100 if e2e_pass_rate <= 1.0 else e2e_pass_rate

    # --- 安装失败或构建失败或启动失败时，功能完整性和稳定性都应为 0 ---
    install_failed = install_status.lower() in ("failed", "failure")
    build_failed = build_status.lower() == "failed"
    launch_failed = launch_status.lower() in ("failed", "failure", "error")
    # 判断是否有实际测试执行数据（用于 launch_failed 时的稳定性评估）
    has_test_runs = e2e_total_count > 0 or e2e_pass_count > 0
    if install_failed or build_failed or launch_failed:
        e2e_rate_100 = 0.0
        # 构建安装启动失败时, 后端完整性也为0
        backend_completeness_val = 0.0 if requires_backend else None
        if build_failed:
            stability_score_100 = 0.0
            usecase_reason = f"构建失败，无法执行E2E测试（{e2e_pass_count}/{e2e_total_count}项通过）"
            stability_reason = "构建失败，应用无法构建，无法评估稳定性"
            backend_completeness_reason = "构建失败，无法评估后端服务" if requires_backend else ""
        elif install_failed:
            stability_score_100 = 0.0
            usecase_reason = f"安装失败，无法执行E2E测试（{e2e_pass_count}/{e2e_total_count}项通过）"
            stability_reason = "安装失败，应用无法安装到设备上，无法评估稳定性"
            backend_completeness_reason = "安装失败，无法评估后端服务" if requires_backend else ""
        else:
            # launch_failed：e2e_rate 强制为0，但稳定性视实际测试数据而定
            if has_test_runs:
                # 有测试执行数据，稳定性基于实际 crash/ANR/白屏 计算
                stability_score_100 = stability_score  # 可为 None（无数据）或实际得分
                usecase_reason = f"应用启动异常但部分测试已执行（{e2e_pass_count}/{e2e_total_count}项通过）"
                backend_completeness_reason = "应用启动状态异常，后端服务验证不完整" if requires_backend else ""
                # 稳定性原因沿用正常路径的逻辑（在下方统一生成）
                if stability_score is None:
                    stability_reason = "应用启动状态异常，稳定性数据未收集"
                elif crash_count == 0 and anr_count == 0 and white_screen_count == 0:
                    stability_reason = "应用启动状态异常，但测试期间无崩溃、无ANR、无白屏"
                else:
                    total_runs = e2e_total_count
                    issue_pct = (crash_count + anr_count + white_screen_count) / total_runs * 100 if total_runs > 0 else 0.0
                    stability_reason = f"应用启动状态异常（崩溃{crash_count}次、ANR{anr_count}次、白屏{white_screen_count}次，问题率{issue_pct:.1f}%）"
            else:
                # 没有任何测试执行，稳定性无法评估，清零
                stability_score_100 = 0.0
                usecase_reason = f"应用未成功启动，无法执行E2E测试（{e2e_pass_count}/{e2e_total_count}项通过）"
                stability_reason = "应用未成功启动，无法评估运行稳定性"
                backend_completeness_reason = "应用未成功启动，无法评估后端服务" if requires_backend else ""
    else:
        # 生成用例完整性原因
        if e2e_total_count == 0:
            usecase_reason = "未执行E2E测试"
        elif e2e_pass_count == e2e_total_count:
            usecase_reason = f"所有核心功能均通过测试（{e2e_pass_count}/{e2e_total_count}项）"
        elif e2e_pass_count > e2e_total_count * QUALITY_USECASE_MOSTLY_PASS_RATIO:
            usecase_reason = f"大部分核心功能通过测试，{e2e_total_count - e2e_pass_count}项未通过（{e2e_pass_count}/{e2e_total_count}项）"
        elif e2e_pass_count > e2e_total_count * QUALITY_USECASE_PARTIAL_PASS_RATIO:
            usecase_reason = f"部分核心功能未实现或失败（{e2e_pass_count}/{e2e_total_count}项通过）"
        else:
            usecase_reason = f"大部分核心功能未实现或失败（{e2e_pass_count}/{e2e_total_count}项通过）"

        # 计算后端完整性（按通过率计分，规则见 dimensions/backend.py）
        backend_completeness_val, backend_completeness_reason = score_backend_completeness(
            requires_backend, real_backend_pass, real_backend_pass_rate,
        )

        # 生成稳定性原因
        total_runs = e2e_total_count
        if stability_score is None:
            # 无稳定性数据
            if build_status == "failed":
                stability_reason = "构建失败，无法评估稳定性"
            else:
                stability_reason = "稳定性数据未收集（平台可能不支持）"
            stability_score_100 = None  # 无数据时保留None，聚合时跳过
        else:
            stability_score_100 = stability_score
            if crash_count == 0 and anr_count == 0 and white_screen_count == 0:
                stability_reason = "无崩溃、无ANR、无白屏，运行稳定"
            elif crash_count == 0 and anr_count == 0 and white_screen_count > 0:
                issue_pct = white_screen_count / total_runs * 100
                if stability_score >= STABILITY_MINOR_ISSUE_SCORE:
                    stability_reason = f"白屏{white_screen_count}次，问题率{issue_pct:.1f}%"
                elif stability_score >= STABILITY_NOTABLE_ISSUE_SCORE:
                    stability_reason = f"存在明显白屏问题（白屏{white_screen_count}次，问题率{issue_pct:.1f}%）"
                else:
                    stability_reason = f"白屏问题严重（白屏{white_screen_count}次，问题率{issue_pct:.1f}%）"
            elif total_runs > 0:
                issue_pct = (crash_count + anr_count + white_screen_count) / total_runs * 100
                if stability_score >= STABILITY_MINOR_ISSUE_SCORE:
                    stability_reason = f"偶发问题但不影响主流程（崩溃{crash_count}次、ANR{anr_count}次、白屏{white_screen_count}次，问题率{issue_pct:.1f}%）"
                elif stability_score >= STABILITY_NOTABLE_ISSUE_SCORE:
                    stability_reason = f"存在明显稳定性问题（崩溃{crash_count}次、ANR{anr_count}次、白屏{white_screen_count}次，问题率{issue_pct:.1f}%）"
                else:
                    stability_reason = f"稳定性严重问题，频繁崩溃或ANR（崩溃{crash_count}次、ANR{anr_count}次、白屏{white_screen_count}次，问题率{issue_pct:.1f}%）"
            else:
                stability_reason = f"崩溃{crash_count}次、ANR{anr_count}次、白屏{white_screen_count}次"

    # --- 减法扣分计算 ---
    base_score = e2e_rate_100  # 基础分 = 用例完整性

    # 稳定性扣分（有数据时才扣）
    stability_deduction = 0.0
    if stability_score_100 is not None:
        stability_deduction = (1 - stability_score_100 / 100.0) * base_score * QUALITY_STABILITY_DEDUCTION_RATIO

    # 后端扣分（需要后端且有数据时才扣）
    backend_deduction = 0.0
    if requires_backend and backend_completeness_val is not None:
        backend_deduction = (1 - backend_completeness_val / 100.0) * base_score * QUALITY_BACKEND_DEDUCTION_RATIO

    composite_score = max(0.0, base_score - stability_deduction - backend_deduction)

    metrics = QualityMetrics(
        usecase_completeness=e2e_rate_100,
        e2e_pass_count=e2e_pass_count,
        e2e_total_count=e2e_total_count,
        stability_score=stability_score_100,
        crash_count=crash_count,
        anr_count=anr_count,
        white_screen_count=white_screen_count,
        crash_free=crash_free,
        compliance_score=0.0,  # 预留,暂不使用
        backend_completeness=backend_completeness_val,
        usecase_reason=usecase_reason,
        stability_reason=stability_reason,
        compliance_reason="该功能暂未接入，后续评估数据安全、隐私合规、上架规范等",
        backend_completeness_reason=backend_completeness_reason,
        stability_deduction=stability_deduction,
        backend_deduction=backend_deduction,
        composite_score=composite_score,
    )

    return metrics
