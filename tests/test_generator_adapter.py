"""测试第三方平台产物的生成器适配器解析。

第三方平台产物以来源名称作为 meta.json 的 ``generator`` 持久化用于展示，
实际执行适配器记录在 ``generator_adapter``（链接 → link_only，安装包 →
tusi）。来源名称未在 GeneratorRegistry 注册，评测时必须回落到适配器名
才能实例化。

覆盖:
- is_generator_registered: 注册名判定（含 entry point 懒加载）
- resolve_generator_adapter: 品牌名回落、显式覆盖优先、各类降级路径
"""

from __future__ import annotations

import json

from evalapp.generators import AppGenerator, GenerationResult, is_generator_registered
from evalapp.services.evaluation import EvaluationService


class _TestGenerator(AppGenerator):
    """仅用于验证注册表行为的自包含测试生成器。"""

    name = "test_adapter"

    def generate(self, prompt_text, platform, **kwargs) -> GenerationResult:
        return GenerationResult(success=True, platform=platform)

    def is_available(self) -> bool:
        return True


def _write_meta(workspace, meta: dict) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False), encoding="utf-8"
    )


class TestIsGeneratorRegistered:
    """测试生成器注册名判定。"""

    def test_generator_subclass_is_registered(self):
        """声明名称的生成器子类应自动注册。"""
        assert is_generator_registered("test_adapter") is True

    def test_builtin_external_is_registered(self):
        """评测仓内置的产物直评占位生成器应已注册。"""
        assert is_generator_registered("external") is True

    def test_source_name_is_not_registered(self):
        """第三方来源名称不是注册名，大小写敏感。"""
        assert is_generator_registered("ExternalProduct") is False

    def test_empty_name_is_not_registered(self):
        """空值不应触发插件加载，直接判否。"""
        assert is_generator_registered("") is False
        assert is_generator_registered(None) is False


class TestResolveGeneratorAdapter:
    """测试来源名称 → 适配器名的解析与降级。"""

    def test_source_name_falls_back_to_adapter(self, tmp_path):
        """来源名称未注册时，按 meta.json 的 generator_adapter 回落。"""
        _write_meta(tmp_path, {"generator": "ExternalProduct", "generator_adapter": "link_only"})
        assert EvaluationService.resolve_generator_adapter(tmp_path, "ExternalProduct") == "link_only"

    def test_package_artifact_falls_back_to_tusi(self, tmp_path):
        """安装包形态的第三方产物回落到 tusi 适配器。"""
        _write_meta(tmp_path, {"generator": "PackageSource", "generator_adapter": "tusi"})
        assert EvaluationService.resolve_generator_adapter(tmp_path, "PackageSource") == "tusi"

    def test_registered_name_wins_over_meta(self, tmp_path):
        """显式传入的已注册名优先，不被 meta.json 干扰。"""
        _write_meta(tmp_path, {"generator": "ExternalProduct", "generator_adapter": "external"})
        assert EvaluationService.resolve_generator_adapter(tmp_path, "test_adapter") == "test_adapter"

    def test_missing_meta_keeps_original_name(self, tmp_path):
        """无 meta.json 时保持原名，交由 get_generator 抛带指引的错误。"""
        assert EvaluationService.resolve_generator_adapter(tmp_path, "ExternalProduct") == "ExternalProduct"

    def test_meta_without_adapter_keeps_original_name(self, tmp_path):
        """meta.json 缺 generator_adapter 字段时保持原名。"""
        _write_meta(tmp_path, {"generator": "ExternalProduct"})
        assert EvaluationService.resolve_generator_adapter(tmp_path, "ExternalProduct") == "ExternalProduct"

    def test_corrupted_meta_does_not_raise(self, tmp_path):
        """meta.json 损坏时降级为原名，不得抛异常中断评测。"""
        tmp_path.mkdir(parents=True, exist_ok=True)
        (tmp_path / "meta.json").write_text("{bad json", encoding="utf-8")
        assert EvaluationService.resolve_generator_adapter(tmp_path, "ExternalProduct") == "ExternalProduct"

    def test_source_name_preserved_by_infer(self, tmp_path):
        """infer_generator_name 仍返回来源名称，保证报告展示真实来源。"""
        _write_meta(tmp_path, {"generator": "ExternalProduct", "generator_adapter": "link_only"})
        assert EvaluationService.infer_generator_name(tmp_path) == "ExternalProduct"
