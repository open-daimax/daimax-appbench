"""关键数据链路集成测试。

覆盖以下五条关键链路，确保跨模块改造后基础链路不被破坏：

1. workspace 原子写入：``atomic_write_json`` 写入后文件内容正确。
2. services 导出：``ReportService`` / ``EvaluationService`` 可正常导入。
3. 数据模型兼容性：新增字段有默认值，旧 JSON 数据可正常反序列化。
4. 评分约束：``score`` 字段对越界值（>100、<0）抛出校验错误。
5. generators 常量：``PLATFORM_INSTRUCTIONS`` 包含所有预期平台。

所有测试相互独立，不依赖物理设备、网络或外部状态，可在 CI 中独立运行。
"""

from __future__ import annotations

import json

import pytest


# ---------------------------------------------------------------------------
# 1) workspace 原子写入测试
# ---------------------------------------------------------------------------


class TestAtomicWriteJson:
    """验证 atomic_write_json 写入数据完整、可被 json.load 反向解析。"""

    def test_atomic_write_json_writes_expected_content(self, tmp_path):
        from evalapp.workspace._safe_io import atomic_write_json

        target = tmp_path / "nested" / "atomic.json"
        payload = {
            "name": "demo",
            "version": 2,
            "items": [1, 2, 3],
            "meta": {"zh": "中文", "en": "english"},
        }

        atomic_write_json(target, payload)

        assert target.exists(), "atomic_write_json 必须真实落盘目标文件"
        with target.open("r", encoding="utf-8") as f:
            loaded = json.load(f)
        assert loaded == payload

    def test_atomic_write_json_overwrites_existing_file(self, tmp_path):
        from evalapp.workspace._safe_io import atomic_write_json

        target = tmp_path / "out.json"
        atomic_write_json(target, {"v": 1})
        atomic_write_json(target, {"v": 2})

        assert json.loads(target.read_text(encoding="utf-8")) == {"v": 2}

    def test_atomic_write_json_leaves_no_tmp_residue(self, tmp_path):
        from evalapp.workspace._safe_io import atomic_write_json

        target = tmp_path / "out.json"
        atomic_write_json(target, {"v": 1})

        # 同目录不应残留以 ".out.json." 开头的临时文件
        residues = [
            p for p in tmp_path.iterdir()
            if p.name.startswith(".out.json.") and p.name.endswith(".tmp")
        ]
        assert residues == [], f"原子写入不应残留临时文件: {residues}"


# ---------------------------------------------------------------------------
# 2) services 导出测试
# ---------------------------------------------------------------------------


class TestServicesExports:
    """验证 services 包对外暴露的关键类可正常导入。"""

    def test_import_report_and_evaluation_services(self):
        from evalapp.services import ReportService, EvaluationService

        assert ReportService is not None
        assert EvaluationService is not None
        # 必须是 class 而不是 None / 模块对象
        assert isinstance(ReportService, type)
        assert isinstance(EvaluationService, type)

    def test_services_all_lists_match(self):
        import evalapp.services as services_pkg

        assert "ReportService" in services_pkg.__all__
        assert "EvaluationService" in services_pkg.__all__


# ---------------------------------------------------------------------------
# 3) 数据模型兼容性测试
# ---------------------------------------------------------------------------


class TestModelBackwardCompatibility:
    """验证 metrics 模型在缺失新字段的旧数据下仍能正常反序列化。"""

    def test_stability_metrics_default_fields(self):
        from evalapp.evaluation.metrics.models import StabilityMetrics

        m = StabilityMetrics()
        # 新增/可选字段必须有默认值
        assert m.crash_count == 0
        assert m.anr_count == 0
        assert m.crash_free is True
        assert m.score == 0.0
        # 新增的白屏字段也应有默认值
        assert m.white_screen_count == 0
        assert m.white_screen_evidence == []

    def test_stability_metrics_loads_legacy_payload(self):
        """旧数据（没有 white_screen_* 等新字段）应可正常反序列化。"""
        from evalapp.evaluation.metrics.models import StabilityMetrics

        legacy_payload = {
            "crash_count": 1,
            "anr_count": 0,
            "total_test_runs": 5,
            "crash_rate": 0.2,
            "anr_rate": 0.0,
            "crash_free": False,
            "score": 60.0,
        }
        m = StabilityMetrics.model_validate(legacy_payload)
        assert m.crash_count == 1
        assert m.score == 60.0
        # 缺失字段使用默认值
        assert m.white_screen_count == 0
        assert m.white_screen_evidence == []
        assert m.crash_events == []

    def test_code_quality_metrics_loads_minimal_payload(self):
        from evalapp.evaluation.metrics.models import CodeQualityMetrics

        m = CodeQualityMetrics.model_validate({})
        assert m.total_issues == 0
        assert m.error_count == 0
        assert m.warning_count == 0


# ---------------------------------------------------------------------------
# 4) 评分约束测试
# ---------------------------------------------------------------------------


class TestScoreConstraints:
    """验证 score 字段对越界值会被 Pydantic 校验拒绝。"""

    def test_score_above_upper_bound_rejected(self):
        from pydantic import ValidationError
        from evalapp.evaluation.metrics.models import StabilityMetrics

        with pytest.raises(ValidationError):
            StabilityMetrics(score=101)

    def test_score_below_lower_bound_rejected(self):
        from pydantic import ValidationError
        from evalapp.evaluation.metrics.models import StabilityMetrics

        with pytest.raises(ValidationError):
            StabilityMetrics(score=-1)

    def test_score_in_range_accepted(self):
        from evalapp.evaluation.metrics.models import StabilityMetrics

        m = StabilityMetrics(score=87.5)
        assert m.score == 87.5

    def test_state_handling_score_constraint(self):
        from pydantic import ValidationError
        from evalapp.evaluation.metrics.models import StateHandlingMetrics

        with pytest.raises(ValidationError):
            StateHandlingMetrics(score=200)
        with pytest.raises(ValidationError):
            StateHandlingMetrics(score=-0.5)


# ---------------------------------------------------------------------------
# 5) generators 常量测试
# ---------------------------------------------------------------------------
# 注：内部版此处另有 TestGeneratorConstants（校验 generation 仓的
# PLATFORM_INSTRUCTIONS 常量），该部分随生成仓迁入 daimax-appbench-gen。
