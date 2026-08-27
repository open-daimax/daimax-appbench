"""Tests for config loading."""

import tempfile
from pathlib import Path

import pytest
import yaml

from evalapp.config import (
    Config,
    get_config,
    load_config,
    reset_config_cache,
    set_config,
)
from evalapp.utils.paths import get_project_root, set_project_root


@pytest.fixture(autouse=True)
def restore_project_root():
    """还原被 set_project_root 改掉的模块级项目根。

    项目根是全局单例，指到 tmp_path 后不还原会让后续依赖仓库内 dataset/ 的
    测试拿到空目录，表现为只在全量执行时失败的偶发错误。
    """
    original = get_project_root()
    yield
    set_project_root(original)
    reset_config_cache()


def test_default_config():
    """Default config should have sensible values."""
    cfg = Config()
    assert cfg.platforms == ["ios", "android"]
    assert cfg.default_generator == ""
    assert cfg.claude.timeout == 3600
    assert cfg.qoder_generator.model == "Performance"
    assert cfg.codex_generator.cli_path == "codex"
    assert cfg.ai_ui_test.timeout == 300
    assert cfg.build_app.build_type == "debug"
    assert cfg.install_app.auto_install is False
    assert cfg.models.e2e.api_key == ""
    # 美观度模型未显式配置时回退硬编码默认值 qwen-vl-max（见 config.py 默认值逻辑）
    assert cfg.models.aesthetics.name == "qwen-vl-max"
    # 通用（生成器无关）配置项默认值：均为空，不内置任何生成器特判
    assert cfg.runtime_error_source == ""
    assert cfg.excluded_workspace_dirs == []
    assert cfg.sample_analysis_generators == []


def test_models_config_explicit():
    """models: 段显式配置时直接生效。"""
    cfg = Config(**{
        "models": {
            "e2e": {
                "api_key": "sk-test",
                "base_url": "https://example.com/v1",
                "name": "model-a",
                "family": "fam-a",
            },
            "aesthetics": {"name": "model-b"},
        },
    })
    assert cfg.models.e2e.api_key == "sk-test"
    assert cfg.models.e2e.name == "model-a"
    assert cfg.models.aesthetics.name == "model-b"


def test_models_config_backfill_from_legacy_fields():
    """未配置 models: 时，从旧字段 ai_ui_test.model_* / claude.aesthetics_model 回填。"""
    cfg = Config(**{
        "ai_ui_test": {
            "model_api_key": "sk-legacy",
            "model_base_url": "https://legacy.example.com/v1",
            "model_name": "legacy-model",
            "model_family": "legacy-fam",
        },
        "claude": {"aesthetics_model": "legacy-aes"},
    })
    assert cfg.models.e2e.api_key == "sk-legacy"
    assert cfg.models.e2e.base_url == "https://legacy.example.com/v1"
    assert cfg.models.e2e.name == "legacy-model"
    assert cfg.models.e2e.family == "legacy-fam"
    assert cfg.models.aesthetics.name == "legacy-aes"


def test_models_config_explicit_wins_over_legacy():
    """models: 显式配置优先于旧字段。"""
    cfg = Config(**{
        "models": {"e2e": {"name": "new-model"}},
        "ai_ui_test": {"model_name": "legacy-model", "model_api_key": "sk-legacy"},
    })
    assert cfg.models.e2e.name == "new-model"
    # 未显式配置的字段仍从旧字段回填
    assert cfg.models.e2e.api_key == "sk-legacy"


def test_load_config_from_yaml():
    """Config should load from a YAML file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        set_project_root(Path(tmpdir))
        config_file = Path(tmpdir) / "evalapp.yaml"
        config_file.write_text(yaml.dump({
            "platforms": ["ios"],
            "default_generator": "custom_gen",
            "claude": {"timeout": 600},
            "build_app": {"build_type": "release"},
            "install_app": {"device_id": "device-1"},
        }))

        cfg = load_config(config_file)
        assert cfg.platforms == ["ios"]
        assert cfg.default_generator == "custom_gen"
        assert cfg.claude.timeout == 600
        assert cfg.build_app.build_type == "release"
        assert cfg.install_app.device_id == "device-1"
        # Unset values should keep defaults
        assert cfg.claude.cli_path == "claude"
        assert cfg.codex_generator.sandbox == "workspace-write"


def test_load_config_default_path_missing_returns_defaults(tmp_path):
    """默认路径 evalapp.yaml 不存在时应静默返回默认配置。"""
    set_project_root(tmp_path)  # 项目根下没有 evalapp.yaml
    cfg = load_config()
    assert cfg.platforms == ["ios", "android"]


def test_load_config_explicit_missing_raises():
    """显式传入 --config 路径但文件不存在应抛 FileNotFoundError。"""
    with pytest.raises(FileNotFoundError):
        load_config("/nonexistent/evalapp.yaml")


def test_get_config_singleton():
    """get_config() 应返回同一份单例实例。"""
    reset_config_cache()
    a = get_config()
    b = get_config()
    assert a is b


def test_get_config_reload_refreshes_cache(tmp_path):
    """reload=True 应重新加载以获取新实例。"""
    set_project_root(tmp_path)
    reset_config_cache()
    a = get_config()
    b = get_config(reload=True)
    assert a is not b


def test_set_config_overrides_cache():
    """set_config() 中的实例会被后续 get_config() 返回。"""
    custom = Config(default_generator="sentinel")
    set_config(custom)
    assert get_config() is custom
    reset_config_cache()

