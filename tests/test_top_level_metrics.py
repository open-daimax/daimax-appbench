"""测试顶层指标计算逻辑的正确性"""

import pytest
from evalapp.evaluation.metrics import (
    compute_success_rate,
    compute_quality,
    compute_experience,
)
from evalapp.evaluation.results.models import PromptResult, EvalRun


class TestSuccessRateCalculation:
    """测试成功率计算逻辑"""
    
    def test_generation_and_launch_success_with_all_tests_pass(self):
        """场景: 生成成功+启动成功+所有测试通过 -> 成功率应该高"""
        # 模拟: gen_ok=True, launch_ok=True, pass_rate=1.0
        result = compute_success_rate(
            initial_rate=1.0,  # 100%通过率
            gen_ok=True,
            launch_ok=True,
        )
        assert result.initial_generation_rate == 100.0
        # 动态权重归一化: 只有initial_generation_rate有值 -> 权重100%
        # composite_score = 100 × (0.6/0.6) = 100.0
        assert result.composite_score == 100.0
    
    def test_generation_and_launch_success_with_half_tests_pass(self):
        """场景: 生成成功+启动成功+50%测试通过 -> 成功率应该是50"""
        result = compute_success_rate(
            initial_rate=0.5,  # 50%通过率
            gen_ok=True,
            launch_ok=True,
        )
        assert result.initial_generation_rate == 50.0
        # 动态权重归一化: 只有initial_generation_rate有值 -> 权重100%
        assert result.composite_score == 50.0
    
    def test_generation_and_launch_success_with_no_tests_pass(self):
        """场景: 生成成功+启动成功+0%测试通过 -> 成功率应该是0"""
        result = compute_success_rate(
            initial_rate=0.0,
            gen_ok=True,
            launch_ok=True,
        )
        assert result.initial_generation_rate == 0.0
        assert result.composite_score == 0.0
    
    def test_generation_failure(self):
        """场景: 生成失败 -> 成功率应该是0"""
        result = compute_success_rate(
            initial_rate=0.0,
            gen_ok=False,
            launch_ok=False,
        )
        assert result.initial_generation_rate == 0.0
        assert result.composite_score == 0.0
        assert "生成失败" in result.initial_generation_reason
    
    def test_launch_failure(self):
        """场景: 生成成功但启动失败 -> 成功率应该是0"""
        result = compute_success_rate(
            initial_rate=0.0,
            gen_ok=True,
            launch_ok=False,
        )
        assert result.initial_generation_rate == 0.0
        assert result.composite_score == 0.0
        assert "启动失败" in result.initial_generation_reason


class TestQualityCalculation:
    """测试质量指标计算逻辑"""
    
    def test_all_tests_pass_no_crashes(self):
        """场景: 所有测试通过+无崩溃 -> 质量分数应该高"""
        result = compute_quality(
            e2e_pass_rate=1.0,  # 100%通过率
            stability_score=100.0,
            e2e_pass_count=5,
            e2e_total_count=5,
            crash_count=0,
            anr_count=0,
            crash_free=True,
        )
        # 用例完整性 = 100, 稳定性 = 100
        # composite = 100 - (1-100/100)*100*0.2 = 100 - 0 = 100
        assert result.usecase_completeness == 100.0
        assert result.stability_score == 100.0
        assert result.composite_score == 100.0
    
    def test_half_tests_pass_no_crashes(self):
        """场景: 50%测试通过+无崩溃 -> 质量分数中等"""
        result = compute_quality(
            e2e_pass_rate=0.5,
            stability_score=100.0,
            e2e_pass_count=3,
            e2e_total_count=6,
            crash_count=0,
            anr_count=0,
            crash_free=True,
        )
        # 用例完整性 = 50, 稳定性 = 100
        # composite = 50 - (1-100/100)*50*0.2 = 50 - 0 = 50
        assert result.usecase_completeness == 50.0
        assert result.stability_score == 100.0
        assert result.composite_score == 50.0
    
    def test_all_tests_pass_with_crashes(self):
        """场景: 所有测试通过+有崩溃 -> 质量分数降低"""
        result = compute_quality(
            e2e_pass_rate=1.0,
            stability_score=70.0,  # 有崩溃，稳定性降低
            e2e_pass_count=5,
            e2e_total_count=5,
            crash_count=2,
            anr_count=0,
            crash_free=False,
        )
        # 用例完整性 = 100, 稳定性 = 70
        # composite = 100 - (1-70/100)*100*0.2 = 100 - 6 = 94
        assert result.usecase_completeness == 100.0
        assert result.stability_score == 70.0
        assert result.composite_score == 94.0
    
    def test_no_test_data(self):
        """场景: 没有测试数据 -> 质量分数应该低"""
        result = compute_quality(
            e2e_pass_rate=0.0,
            stability_score=None,  # 无稳定性数据
            e2e_pass_count=0,
            e2e_total_count=0,
            crash_count=0,
            anr_count=0,
            crash_free=True,
        )
        # 用例完整性 = 0, 稳定性无数据=None
        # composite = 0 - 0(无稳定性不扣分) = 0
        assert result.usecase_completeness == 0.0
        assert result.stability_score is None
        assert result.composite_score == 0.0
        assert "未执行E2E测试" in result.usecase_reason


class TestBuildFailureScenario:
    """测试构建失败场景的评分逻辑"""
    
    def test_build_failure_should_score_zero(self):
        """场景: 构建失败 -> 成功率和质量都应该是0分"""
        run = EvalRun(
            generator_name="test",
            run_type="sample",
        )
        
        # 模拟构建失败的PromptResult
        pr = PromptResult(
            prompt_id="sample_001",
            platform="ios",
            generator_name="test",
            item_type="sample",
            generation_success=False,  # 构建失败
            pass_count=0,
            fail_count=0,
            total_count=0,  # 没有执行测试
            error_message="Build failed: compilation error",
        )
        
        # 手动计算指标(模拟evaluator的逻辑)
        # 成功率: generation_success=False -> 0分
        pr.success_rate = compute_success_rate(
            initial_rate=0.0,
            gen_ok=False,
            launch_ok=False,
        )
        
        # 质量: 没有测试数据 -> 0分
        pr.quality = compute_quality(
            e2e_pass_rate=0.0,
            stability_score=None,
            e2e_pass_count=0,
            e2e_total_count=0,
        )
        
        pr.experience = compute_experience(duration_ms=120000)
        
        run.prompt_results.append(pr)
        run.compute_summary()
        
        tls = run.summary.top_level_summary
        assert tls['sample_count'] == 1
        # 构建失败: 成功率=0
        assert tls['mean_success_rate'] == 0.0
        assert tls['mean_functionality_completeness'] == 0.0
        # E2E通过率: 没有测试 -> 0
        assert tls['e2e_pass_rate'] == 0.0
    
    def test_mixed_build_success_and_failure(self):
        """场景: 混合构建成功和失败的情况"""
        run = EvalRun(
            generator_name="test",
            run_type="sample",
        )
        
        # 样本1: 构建成功,测试全过
        pr1 = PromptResult(
            prompt_id="sample_001",
            platform="ios",
            generator_name="test",
            item_type="sample",
            generation_success=True,
            pass_count=5,
            fail_count=0,
            total_count=5,
        )
        pr1.success_rate = compute_success_rate(1.0, gen_ok=True, launch_ok=True)
        pr1.quality = compute_quality(
            e2e_pass_rate=1.0,
            stability_score=100.0,
            e2e_pass_count=5,
            e2e_total_count=5,
        )
        pr1.experience = compute_experience(duration_ms=300000)
        
        # 样本2: 构建失败
        pr2 = PromptResult(
            prompt_id="sample_002",
            platform="ios",
            generator_name="test",
            item_type="sample",
            generation_success=False,
            pass_count=0,
            fail_count=0,
            total_count=0,
            error_message="Build failed",
        )
        pr2.success_rate = compute_success_rate(0.0, gen_ok=False, launch_ok=False)
        pr2.quality = compute_quality(
            e2e_pass_rate=0.0,
            stability_score=None,
            e2e_pass_count=0,
            e2e_total_count=0,
        )
        pr2.experience = compute_experience(duration_ms=60000)
        
        run.prompt_results.extend([pr1, pr2])
        run.compute_summary()
        
        tls = run.summary.top_level_summary
        assert tls['sample_count'] == 2
        # 成功率平均: (100 + 0) / 2 = 50 (动态权重: 只有initial时composite=initial_rate本身)
        assert tls['mean_success_rate'] == 50.0
        # 质量平均: (100 + 0) / 2 = 50
        assert tls['mean_functionality_completeness'] == 50.0
        # E2E总通过率: 5/5 = 100% (只有样本1有测试)
        assert tls['e2e_pass_rate'] == 100.0
        # 稳定性平均: 只有样本1有测试数据
        assert tls['mean_stability_score'] == 100.0


class TestTopLevelAggregation:
    """测试顶层指标汇总逻辑"""
    
    def test_single_sample_all_pass(self):
        """单个样本,所有指标满分"""
        run = EvalRun(
            generator_name="test",
            run_type="sample",
        )
        
        # 创建一个成功的PromptResult
        pr = PromptResult(
            prompt_id="sample_001",
            platform="ios",
            generator_name="test",
            item_type="sample",
            generation_success=True,
            pass_count=5,
            fail_count=0,
            total_count=5,
        )
        # 手动设置指标
        pr.success_rate = compute_success_rate(1.0, gen_ok=True, launch_ok=True)
        pr.quality = compute_quality(
            e2e_pass_rate=1.0,
            stability_score=100.0,
            e2e_pass_count=5,
            e2e_total_count=5,
        )
        pr.experience = compute_experience(duration_ms=300000)  # 5分钟
        
        run.prompt_results.append(pr)
        run.compute_summary()
        
        tls = run.summary.top_level_summary
        assert tls['sample_count'] == 1
        # 动态权重归一化: initial_rate=100, 其他未实现 -> composite=100
        assert tls['mean_success_rate'] == 100.0
        assert tls['mean_functionality_completeness'] == 100.0
        # experience分数取决于耗时,5分钟应该是高分
        assert tls['mean_experience'] > 85
        assert tls['e2e_pass_rate'] == 100.0
    
    def test_single_sample_all_fail(self):
        """单个样本,测试全部失败"""
        run = EvalRun(
            generator_name="test",
            run_type="sample",
        )
        
        pr = PromptResult(
            prompt_id="sample_001",
            platform="ios",
            generator_name="test",
            item_type="sample",
            generation_success=True,
            pass_count=0,
            fail_count=5,
            total_count=5,
        )
        # 成功率应该基于pass_rate=0
        pr.success_rate = compute_success_rate(0.0, gen_ok=True, launch_ok=True)
        pr.quality = compute_quality(
            e2e_pass_rate=0.0,
            stability_score=100.0,
            e2e_pass_count=0,
            e2e_total_count=5,
        )
        pr.experience = compute_experience(duration_ms=600000)  # 10分钟
        
        run.prompt_results.append(pr)
        run.compute_summary()
        
        tls = run.summary.top_level_summary
        assert tls['sample_count'] == 1
        assert tls['mean_success_rate'] == 0.0  # 修复后: 测试全败应该0分
        assert tls['mean_functionality_completeness'] == 0.0  # 用例完整性0, 稳定性扣分=(1-1)*0*0.2=0, composite=0
        assert tls['e2e_pass_rate'] == 0.0
    
    def test_multiple_samples_average(self):
        """多个样本,测试平均逻辑"""
        run = EvalRun(
            generator_name="test",
            run_type="sample",
        )
        
        # 样本1: 全通过
        pr1 = PromptResult(
            prompt_id="sample_001",
            platform="ios",
            generator_name="test",
            item_type="sample",
            generation_success=True,
            pass_count=5,
            fail_count=0,
            total_count=5,
        )
        pr1.success_rate = compute_success_rate(1.0, gen_ok=True, launch_ok=True)
        pr1.quality = compute_quality(
            e2e_pass_rate=1.0,
            stability_score=100.0,
            e2e_pass_count=5,
            e2e_total_count=5,
        )
        pr1.experience = compute_experience(duration_ms=300000)
        
        # 样本2: 全失败
        pr2 = PromptResult(
            prompt_id="sample_002",
            platform="ios",
            generator_name="test",
            item_type="sample",
            generation_success=True,
            pass_count=0,
            fail_count=5,
            total_count=5,
        )
        pr2.success_rate = compute_success_rate(0.0, gen_ok=True, launch_ok=True)
        pr2.quality = compute_quality(
            e2e_pass_rate=0.0,
            stability_score=100.0,
            e2e_pass_count=0,
            e2e_total_count=5,
        )
        pr2.experience = compute_experience(duration_ms=600000)
        
        run.prompt_results.extend([pr1, pr2])
        run.compute_summary()
        
        tls = run.summary.top_level_summary
        assert tls['sample_count'] == 2
        # 成功率平均: (100 + 0) / 2 = 50 (动态权重: initial=100时composite=100)
        assert tls['mean_success_rate'] == 50.0
        # 质量平均: (100 + 0) / 2 = 50
        assert tls['mean_functionality_completeness'] == 50.0
        # E2E总通过率: 5/10 = 50%
        assert tls['e2e_pass_rate'] == 50.0
    
    def test_samples_with_and_without_tests(self):
        """混合场景: 有测试样本和无测试样本"""
        run = EvalRun(
            generator_name="test",
            run_type="sample",
        )
        
        # 样本1: 有测试且全通过
        pr1 = PromptResult(
            prompt_id="sample_001",
            platform="ios",
            generator_name="test",
            item_type="sample",
            generation_success=True,
            pass_count=5,
            fail_count=0,
            total_count=5,
        )
        pr1.success_rate = compute_success_rate(1.0, gen_ok=True, launch_ok=True)
        pr1.quality = compute_quality(
            e2e_pass_rate=1.0,
            stability_score=100.0,
            e2e_pass_count=5,
            e2e_total_count=5,
        )
        pr1.experience = compute_experience(duration_ms=300000)
        
        # 样本2: 没有测试
        pr2 = PromptResult(
            prompt_id="sample_002",
            platform="ios",
            generator_name="test",
            item_type="sample",
            generation_success=True,
            pass_count=0,
            fail_count=0,
            total_count=0,  # 无测试
        )
        # 无测试时,成功率应该等于initial_rate本身(动态权重归一化)
        pr2.success_rate = compute_success_rate(0.6, gen_ok=True, launch_ok=True)
        pr2.quality = compute_quality(
            e2e_pass_rate=0.0,
            stability_score=None,  # 无稳定性数据
            e2e_pass_count=0,
            e2e_total_count=0,
        )
        pr2.experience = compute_experience(duration_ms=300000)
        
        run.prompt_results.extend([pr1, pr2])
        run.compute_summary()
        
        tls = run.summary.top_level_summary
        assert tls['sample_count'] == 2
        # 成功率平均: (100 + 60) / 2 = 80 (动态权重: composite=initial_rate本身)
        assert tls['mean_success_rate'] == 80.0
        # 质量平均: 样本1=100, 样本2=0 -> (100+0)/2 = 50
        assert tls['mean_functionality_completeness'] == 50.0
        # E2E总通过率: 5/5 = 100% (只计算有测试的)
        assert tls['e2e_pass_rate'] == 100.0
        # 稳定性平均: 只计算有测试的样本(样本1)
        assert tls['mean_stability_score'] == 100.0


class TestInstallFailureScenario:
    """测试安装失败场景的评分逻辑"""
    
    def test_install_failure_quality_should_be_zero(self):
        """场景: 安装失败 -> 质量分数应该为0（功能完整性和稳定性都为0）"""
        result = compute_quality(
            e2e_pass_rate=0.0,
            stability_score=100.0,  # 即使原始稳定性为100
            e2e_pass_count=0,
            e2e_total_count=2,
            crash_count=0,
            anr_count=0,
            crash_free=True,
            install_status="failed",
        )
        assert result.usecase_completeness == 0.0
        assert result.stability_score == 0.0
        assert result.composite_score == 0.0
        assert "安装失败" in result.usecase_reason
        assert "安装失败" in result.stability_reason
    
    def test_install_success_normal_scoring(self):
        """场景: 安装成功 -> 正常计算质量分数"""
        result = compute_quality(
            e2e_pass_rate=0.5,
            stability_score=100.0,
            e2e_pass_count=3,
            e2e_total_count=6,
            crash_count=0,
            anr_count=0,
            crash_free=True,
            install_status="success",
        )
        assert result.usecase_completeness == 50.0
        assert result.stability_score == 100.0
        assert result.composite_score == 50.0
    
    def test_install_skipped_normal_scoring(self):
        """场景: 安装跳过（如小程序） -> 正常计算质量分数"""
        result = compute_quality(
            e2e_pass_rate=0.5,
            stability_score=100.0,
            e2e_pass_count=3,
            e2e_total_count=6,
            crash_count=0,
            anr_count=0,
            crash_free=True,
            install_status="skipped",
        )
        assert result.usecase_completeness == 50.0
        assert result.stability_score == 100.0
        assert result.composite_score == 50.0


class TestDynamicWeightNormalization:
    """测试动态权重归一化逻辑"""

    def test_only_initial_rate_active(self):
        """只有initial_generation_rate有值时，composite_score等于initial_rate本身"""
        result = compute_success_rate(
            initial_rate=0.8,
            gen_ok=True,
            launch_ok=True,
        )
        assert result.initial_generation_rate == 80.0
        # 动态权重: 只有initial有值 -> 权重归一化为100%
        assert result.composite_score == 80.0

    def test_initial_and_issue_fix_active(self):
        """initial和issue_fix都有值时，按0.6/0.2归一化"""
        result = compute_success_rate(
            initial_rate=1.0,
            issue_fix_rate=0.5,
            gen_ok=True,
            launch_ok=True,
        )
        assert result.initial_generation_rate == 100.0
        assert result.issue_fix_rate == 50.0
        # 权重归一化: 0.6/(0.6+0.2) + 0.2/(0.6+0.2) = 0.75/0.25
        # composite = 100 × 0.75 + 50 × 0.25 = 75 + 12.5 = 87.5
        assert result.composite_score == 87.5

    def test_initial_and_req_ext_active(self):
        """initial和requirement_extension都有值时，按0.6/0.2归一化"""
        result = compute_success_rate(
            initial_rate=1.0,
            requirement_extension_rate=0.8,
            gen_ok=True,
            launch_ok=True,
        )
        assert result.initial_generation_rate == 100.0
        assert result.requirement_extension_rate == 80.0
        # 权重归一化: 0.6/(0.6+0.2) + 0.2/(0.6+0.2) = 0.75/0.25
        # composite = 100 × 0.75 + 80 × 0.25 = 75 + 20 = 95.0
        assert result.composite_score == 95.0

    def test_all_three_active(self):
        """三个指标都有值时，使用标准0.6/0.2/0.2权重"""
        result = compute_success_rate(
            initial_rate=1.0,
            issue_fix_rate=0.5,
            requirement_extension_rate=0.8,
            gen_ok=True,
            launch_ok=True,
        )
        assert result.initial_generation_rate == 100.0
        assert result.issue_fix_rate == 50.0
        assert result.requirement_extension_rate == 80.0
        # 标准权重: 100 × 0.6 + 50 × 0.2 + 80 × 0.2 = 60 + 10 + 16 = 86.0
        assert result.composite_score == 86.0

    def test_issue_fix_zero_excluded(self):
        """issue_fix_rate=0时应被排除，不参与权重"""
        result = compute_success_rate(
            initial_rate=0.5,
            issue_fix_rate=0.0,
            requirement_extension_rate=0.0,
            gen_ok=True,
            launch_ok=True,
        )
        # 只有initial有值 -> composite = initial_rate本身
        assert result.composite_score == 50.0

    def test_initial_zero_still_counted(self):
        """initial_generation_rate=0时仍参与权重（核心指标始终活跃）"""
        result = compute_success_rate(
            initial_rate=0.0,
            issue_fix_rate=0.8,
            requirement_extension_rate=0.6,
            gen_ok=False,
            launch_ok=False,
        )
        # initial始终活跃, 其他两个也>0, 三项都参与
        # composite = 0 × (0.6/1.0) + 80 × (0.2/1.0) + 60 × (0.2/1.0) = 0 + 16 + 12 = 28.0
        assert result.composite_score == 28.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class TestQualityDeductionEdgeCases:
    """测试减法扣分公式的边界情况"""

    def test_stability_none_no_deduction(self):
        """稳定性数据缺失(None) -> 不扣稳定性分"""
        result = compute_quality(
            e2e_pass_rate=0.8,
            stability_score=None,
            e2e_pass_count=4,
            e2e_total_count=5,
        )
        assert result.usecase_completeness == 80.0
        assert result.stability_score is None
        assert result.stability_deduction == 0.0
        assert result.backend_deduction == 0.0
        # composite = 80 - 0 - 0 = 80
        assert result.composite_score == 80.0

    def test_no_backend_no_deduction(self):
        """不需要后端(requires_backend=False) -> 不扣后端分"""
        result = compute_quality(
            e2e_pass_rate=0.8,
            stability_score=60.0,
            e2e_pass_count=4,
            e2e_total_count=5,
            requires_backend=False,
        )
        assert result.usecase_completeness == 80.0
        # stability_deduction = (1-60/100)*80*0.2 = 0.4*80*0.2 = 6.4
        assert result.stability_deduction == pytest.approx(6.4)
        assert result.backend_deduction == 0.0
        # composite = 80 - 6.4 = 73.6
        assert result.composite_score == pytest.approx(73.6)

    def test_with_backend_deduction(self):
        """需要后端且有数据 -> 同时扣稳定性和后端分"""
        result = compute_quality(
            e2e_pass_rate=0.8,
            stability_score=60.0,
            e2e_pass_count=4,
            e2e_total_count=5,
            requires_backend=True,
            real_backend_pass_rate=0.7,
        )
        assert result.usecase_completeness == 80.0
        # stability_deduction = (1-0.6)*80*0.2 = 6.4
        assert result.stability_deduction == pytest.approx(6.4)
        # backend_deduction = (1-70/100)*80*0.3 = 0.3*80*0.3 = 7.2
        assert result.backend_deduction == pytest.approx(7.2)
        # composite = 80 - 6.4 - 7.2 = 66.4
        assert result.composite_score == pytest.approx(66.4)

    def test_stability_zero_max_deduction(self):
        """稳定性=0时最多扣20%基础分"""
        result = compute_quality(
            e2e_pass_rate=1.0,
            stability_score=0.0,
            e2e_pass_count=5,
            e2e_total_count=5,
            requires_backend=False,
        )
        # stability_deduction = (1-0)*100*0.2 = 20
        assert result.stability_deduction == pytest.approx(20.0)
        assert result.backend_deduction == 0.0
        # composite = 100 - 20 = 80
        assert result.composite_score == pytest.approx(80.0)

    def test_backend_zero_max_deduction(self):
        """后端=0时最多扣30%基础分"""
        result = compute_quality(
            e2e_pass_rate=1.0,
            stability_score=0.0,
            e2e_pass_count=5,
            e2e_total_count=5,
            requires_backend=True,
            real_backend_pass_rate=0.0,
        )
        # stability_deduction = (1-0)*100*0.2 = 20
        # backend_deduction = (1-0)*100*0.3 = 30
        assert result.stability_deduction == pytest.approx(20.0)
        assert result.backend_deduction == pytest.approx(30.0)
        # composite = 100 - 20 - 30 = 50 (最多扣50%)
        assert result.composite_score == pytest.approx(50.0)

    def test_composite_floor_at_zero(self):
        """composite 最低为0，不会为负"""
        # 构造一个base_score很低但扣分比例很高的场景
        # 实际上由于扣分是base_score的比例，base=0时扣分也为0
        # 所以构造 build_failed 场景: base=0, stability=0
        result = compute_quality(
            e2e_pass_rate=0.0,
            stability_score=0.0,
            e2e_pass_count=0,
            e2e_total_count=5,
            requires_backend=True,
            real_backend_pass_rate=0.0,
        )
        assert result.composite_score >= 0.0

    def test_requires_backend_no_data_zero_deduction(self):
        """需要后端但无数据(real_backend_pass_rate=None) -> 后端分0，扣分30%"""
        result = compute_quality(
            e2e_pass_rate=1.0,
            stability_score=100.0,
            e2e_pass_count=5,
            e2e_total_count=5,
            requires_backend=True,
            real_backend_pass_rate=None,
            real_backend_pass=None,
        )
        # backend_completeness = 0 (数据缺失)
        # backend_deduction = (1-0/100)*100*0.3 = 30
        assert result.backend_deduction == pytest.approx(30.0)
        # composite = 100 - 0(稳定性满分) - 30 = 70
        assert result.composite_score == pytest.approx(70.0)
