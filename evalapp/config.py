"""Configuration loading for EvalApp."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, PrivateAttr, model_validator

from .utils.paths import get_project_root

logger = logging.getLogger(__name__)


def _resolve_script_path(path_str: str) -> str:
    """Resolve relative script paths against the project root."""
    p = Path(path_str).expanduser()
    if not p.is_absolute():
        p = get_project_root() / p
    return str(p)


class GeneratorConfig(BaseModel):
    """Configuration for a specific generator."""
    # 生成器仓库地址：开源版不内置任何内部仓库默认值，
    # 由生成器插件（如 daimax-appbench-gen）自行解析或通过配置文件指定。
    git_repo: str = ""
    branch: str = "dev"  # 默认使用 dev 分支
    build_command: str = "npm run build"  # 生成器仓库编译命令


class ClaudeCLIGeneratorConfig(BaseModel):
    """Configuration for Claude CLI as an app generator.

    Reference: https://code.claude.com/docs/zh-CN/cli-reference
    """
    cli_path: str = "claude"
    workspace_root: str = "~/claude_projects"
    timeout: int = Field(default=3600, gt=0)
    system_prompt: str = ""


class QoderCLIGeneratorConfig(BaseModel):
    """Configuration for Qoder CLI as an app generator."""

    cli_path: str = "qodercli"
    workspace_root: str = "~/qoder_projects"
    timeout: int = Field(default=3600, gt=0)
    model: str = "Performance"
    system_prompt: str = ""


class CodexCLIGeneratorConfig(BaseModel):
    """Configuration for OpenAI Codex CLI as an app generator."""

    cli_path: str = "codex"
    workspace_root: str = "~/codex_projects"
    timeout: int = Field(default=3600, gt=0)
    model: str = ""
    base_url: str = ""
    api_key: str = ""
    api_key_env: str = "CODEX_API_KEY"
    sandbox: Literal["read-only", "workspace-write", "danger-full-access"] = "workspace-write"
    system_prompt: str = ""


class OpenCodeCLIGeneratorConfig(BaseModel):
    """Configuration for OpenCode CLI as an app generator.

    复用 DashScope OpenAI-compatible 端点：``base_url`` / ``model`` 必须显式配置，
    ``api_key`` 优先取 ``api_key_env`` 指定的环境变量（默认 ``CODEX_API_KEY``）。
    自定义 provider 由 client 经 ``OPENCODE_CONFIG_CONTENT`` 内联注入，密钥不落地文件。
    """

    cli_path: str = "opencode"
    workspace_root: str = "~/opencode_projects"
    timeout: int = Field(default=3600, gt=0)
    model: str = ""
    base_url: str = ""
    api_key: str = ""
    api_key_env: str = "CODEX_API_KEY"
    system_prompt: str = ""


class ClaudeConfig(BaseModel):
    """Claude Code CLI configuration.

    The evaluation framework itself does not consume cli_path/timeout;
    they are configuration contracts depended upon by generator-side plugins
    (e.g., evalgen's Claude generator and test case design injection).
    Only required when a generator plugin is installed.
    """
    cli_path: str = "claude"
    timeout: int = Field(default=3600, gt=0)
    # 已迁移至 models.aesthetics.name，仅保留向后兼容（由 Config 校验器回填）
    aesthetics_model: str = ""


class ModelEndpointConfig(BaseModel):
    """Configuration for a single model endpoint (organized by usage slot)."""

    api_key: str = ""
    base_url: str = ""
    name: str = ""
    family: str = ""


class ModelsConfig(BaseModel):
    """Unified model configuration table organized by usage slot.

    Slots:
      * ``e2e``        — Midscene E2E UI test vision model (requires api_key/base_url/name/family).
      * ``aesthetics`` — Aesthetics scoring model (only name needed; empty uses tool default).

    Legacy fields ``ai_ui_test.model_*`` and ``claude.aesthetics_model`` are still
    recognized; when models is not explicitly configured, values are back-filled
    automatically (see Config._fill_models_from_legacy).
    """

    e2e: ModelEndpointConfig = Field(default_factory=ModelEndpointConfig)
    aesthetics: ModelEndpointConfig = Field(default_factory=ModelEndpointConfig)


class AIUITestConfig(BaseModel):
    """Configuration for the built-in ai-ui-test tool."""

    script_dir: str = ""  # 默认为空，由executor.py自动解析为内置工具路径
    timeout: int = Field(default=300, gt=0)
    replan_limit: int = Field(default=20, ge=0)
    max_retries: int = Field(default=1, ge=0)  # 单个测试用例失败后的最大重试次数（0=不重试）
    # 同一设备/项目下多个 TC（Test Case）的并发数。
    # 默认 1 保持向后兼容；>1 时使用 ThreadPoolExecutor 在同一设备池中并行执行 TC。
    # 注意：同一设备并发执行多个 TC 可能彼此干扰，请评估业务场景后再调高。
    max_parallel_tc: int = Field(default=1, ge=1)
    # ── 工具初始化与服务起动超时配置（取代代码中的硬编码数字）──
    npm_install_timeout: int = Field(default=300, gt=0)  # ai-ui-test 首次初始化时 npm install 超时（秒）
    npm_build_timeout: int = Field(default=120, gt=0)    # ai-ui-test TypeScript 编译超时（秒）
    port_wait_timeout: float = Field(default=10.0, gt=0)  # 本地 H5 服务启动后等待端口可连接的超时（秒）
    serve_shutdown_timeout: int = Field(default=5, gt=0)  # 关闭 H5 本地服务进程的等待超时（秒）
    # Midscene 模型配置（已迁移至顶层 models.e2e，仅保留向后兼容）
    model_api_key: str = ""
    model_base_url: str = ""
    model_name: str = ""
    model_family: str = ""


class BuildAppConfig(BaseModel):
    """Configuration for the built-in build-app tool."""

    script_path: str = "tools/build_app/scripts/build_app.py"
    timeout: int = Field(default=3600, gt=0)
    build_type: Literal["debug", "release"] = "debug"
    clean: bool = False
    android_output_format: str = "apk"
    ios_output_format: str = "app"
    max_retries: int = Field(default=1, ge=0)  # 构建失败后的最大重试次数（0=不重试）


class InstallAppConfig(BaseModel):
    """Configuration for the built-in install-app tool."""

    script_path: str = "tools/install_app/scripts/install_app.py"
    timeout: int = Field(default=300, gt=0)
    device_id: str | None = None
    auto_install: bool = False
    auto_uninstall: bool = True  # 评测完成后自动卸载应用，默认开启
    max_devices: int = Field(default=5, ge=1, le=10)  # 并发 E2E 测试时最大模拟器/设备实例数
    max_retries: int = Field(default=1, ge=0)  # 安装失败后的最大重试次数（0=不重试）


class ExternalServiceConfig(BaseModel):
    """Optional external model service configuration.

    An external model service can provide advanced evaluation capabilities (e.g.,
    enhanced code analysis, multimodal evaluation) on top of the built-in tools.
    Disabled by default; enable by setting ``enabled: true`` and providing
    ``api_key`` in evalapp.yaml. When disabled or unconfigured, evaluation falls
    back to the built-in tools.
    """

    enabled: bool = False
    api_key: str = ""  # 环境变量 EXTERNAL_SERVICE_API_KEY 可覆盖

    @property
    def effective_api_key(self) -> str:
        """Return the effective API key (environment variable takes precedence)."""
        import os
        return os.environ.get("EXTERNAL_SERVICE_API_KEY", "") or self.api_key


class MCPServerConfig(BaseModel):
    """Configuration for a single MCP server endpoint."""

    name: str = ""               # 服务名称标识，如 "filesystem", "database"
    command: str = ""            # MCP 服务启动命令，如 "npx", "python"
    args: list[str] = Field(default_factory=list)  # 启动命令参数
    env: dict[str, str] = Field(default_factory=dict)  # 传递给服务进程的环境变量
    url: str = ""                # 远程 MCP 服务 URL（与 command 二选一）


class MCPConfig(BaseModel):
    """MCP (Model Context Protocol) tool service configuration.

    MCP allows the evaluation framework to invoke external tool services
    (filesystem, database, API gateway, etc.), extending evaluation capabilities.
    Disabled by default; once enabled, register server endpoints in the
    ``servers`` list.

    See :file:`references/MCP_TOOLS_REFERENCE.md` for integration instructions.
    """

    enabled: bool = False
    servers: list[MCPServerConfig] = Field(default_factory=list)


class ReportConfig(BaseModel):
    """Configuration for report generation and display."""

    auto_open: bool = True  # 生成报告后自动在浏览器中打开
    eval_version: str = "2.0"  # 评测版本号


class Config(BaseModel):
    """Top-level EvalApp configuration."""

    model_config = {"extra": "allow"}  # 允许多余字段，在 validator 中 warning

    platforms: list[str] = Field(default_factory=lambda: ["ios", "android"])
    default_generator: str = ""  # Must be set via config file or CLI
    prompts_dir: str = "prompts"
    test_cases_dir: str = "test_cases"
    results_dir: str = "results"  # 已弃用：数据源统一为 workspace，此字段仅保留向后兼容
    stream_output: bool = False
    # 评测结果输出根路径（workspace_manager 使用），默认 ~/eval_app_factory
    workspace_root: str = "~/eval_app_factory"
    # 缓存 TTL 配置（秒）
    cache_ttl_list: int = Field(default=8, ge=0)
    cache_ttl_report: int = Field(default=30, ge=0)
    generator: GeneratorConfig = Field(default_factory=GeneratorConfig)
    claude: ClaudeConfig = Field(default_factory=ClaudeConfig)
    models: ModelsConfig = Field(default_factory=ModelsConfig)
    ai_ui_test: AIUITestConfig = Field(default_factory=AIUITestConfig)
    build_app: BuildAppConfig = Field(default_factory=BuildAppConfig)
    install_app: InstallAppConfig = Field(default_factory=InstallAppConfig)
    report: ReportConfig = Field(default_factory=ReportConfig)
    external_service: ExternalServiceConfig = Field(
        default_factory=ExternalServiceConfig
    )
    mcp: MCPConfig = Field(default_factory=MCPConfig)
    claude_generator: ClaudeCLIGeneratorConfig = Field(
        default_factory=ClaudeCLIGeneratorConfig
    )
    qoder_generator: QoderCLIGeneratorConfig = Field(
        default_factory=QoderCLIGeneratorConfig
    )
    codex_generator: CodexCLIGeneratorConfig = Field(
        default_factory=CodexCLIGeneratorConfig
    )
    opencode_generator: OpenCodeCLIGeneratorConfig = Field(
        default_factory=OpenCodeCLIGeneratorConfig
    )

    # 运行时注入字段（不参与序列化，由命令行 setup 设置）
    _generator_cli_path: str | None = PrivateAttr(default=None)

    # ── 通用配置项（生成器无关） ──
    # 被测应用运行时经 console.error 上报的 source 标识；空则不采集运行时错误
    runtime_error_source: str = ""
    # 扫描/聚合产物时需排除的工作区子目录名；空则不额外排除
    excluded_workspace_dirs: list[str] = Field(default_factory=list)
    # 需要运行 SampleAnalyzer.summarize 的生成器名单；空则都不运行
    sample_analysis_generators: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _warn_extra_fields(cls, data: dict) -> dict:
        """检测并报告 YAML 中未被 Pydantic 模型消费的多余字段。"""
        if not isinstance(data, dict):
            return data
        known_fields = set(cls.model_fields.keys())
        extra_keys = set(data.keys()) - known_fields
        if extra_keys:
            logger.warning(
                "配置文件中存在未识别的字段（将被忽略）：%s。"
                "如需使用请先在 Config 模型中定义对应字段。",
                ", ".join(sorted(extra_keys)),
            )
        return data

    @model_validator(mode="after")
    def _fill_models_from_legacy(self) -> "Config":
        """旧字段向后兼容：未配置 models 槽位时从旧位置回填。

        优先级：models.* 显式配置 > 旧字段（ai_ui_test.model_* / claude.aesthetics_model）。
        """
        e2e = self.models.e2e
        if not e2e.api_key and self.ai_ui_test.model_api_key:
            e2e.api_key = self.ai_ui_test.model_api_key
        if not e2e.base_url and self.ai_ui_test.model_base_url:
            e2e.base_url = self.ai_ui_test.model_base_url
        if not e2e.name and self.ai_ui_test.model_name:
            e2e.name = self.ai_ui_test.model_name
        if not e2e.family and self.ai_ui_test.model_family:
            e2e.family = self.ai_ui_test.model_family

        if not self.models.aesthetics.name and self.claude.aesthetics_model:
            self.models.aesthetics.name = self.claude.aesthetics_model

        # ── 美观度模型硬编码默认值（DashScope qwen-vl-max）──
        # 优先级：显式 YAML 配置 > 旧字段回填 > 硬编码默认值
        # 确保开源后无 evalapp.yaml 也能开箱即用
        if not self.models.aesthetics.base_url:
            self.models.aesthetics.base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
        if not self.models.aesthetics.name:
            self.models.aesthetics.name = "qwen-vl-max"
        return self


    @property
    def prompts_path(self) -> Path:
        return get_project_root() / self.prompts_dir

    @property
    def test_cases_path(self) -> Path:
        return get_project_root() / self.test_cases_dir

    @property
    def results_path(self) -> Path:
        """Deprecated: data source unified to workspace; kept for backward compatibility."""
        return get_project_root() / self.results_dir

    @property
    def eval_workspace_path(self) -> Path:
        """Root path for evaluation output (used by workspace_manager)."""
        return Path(self.workspace_root).expanduser()

    @property
    def claude_workspace_root_path(self) -> Path:
        return Path(self.claude_generator.workspace_root).expanduser()

    @property
    def qoder_workspace_root_path(self) -> Path:
        return Path(self.qoder_generator.workspace_root).expanduser()

    @property
    def codex_workspace_root_path(self) -> Path:
        return Path(self.codex_generator.workspace_root).expanduser()

    @property
    def opencode_workspace_root_path(self) -> Path:
        return Path(self.opencode_generator.workspace_root).expanduser()



# ---------------------------------------------------------------------------
# 配置加载（内部 / 单例）
# ---------------------------------------------------------------------------

# 模块级单例缓存。外部应通过 get_config() 获取，不要直接读取该变量。
_cached_config: Config | None = None


def load_config(path: str | Path | None = None) -> Config:
    """[Internal] Load configuration from YAML file.

    General business code should use :func:`get_config` to obtain the global
    singleton. This function is only used internally in these scenarios:
      * The CLI entry point needs to explicitly load a file specified via ``--config``.
      * Test code needs to bypass the singleton cache and load independently.

    Behavior:
      * ``path is None``: attempts to load ``evalapp.yaml`` from the project root;
        silently returns a default :class:`Config` if the file does not exist
        (backward compatible).
      * ``path`` is explicitly provided by the caller but the file does not exist:
        raises ``FileNotFoundError`` to avoid silently losing user input.
    """
    explicit = path is not None
    if path is None:
        path = get_project_root() / "evalapp.yaml"
    else:
        path = Path(path)

    if not path.exists():
        if explicit:
            raise FileNotFoundError(
                f"指定的配置文件不存在: {path}（请检查 --config 参数）"
            )
        return Config()

    try:
        with open(path, encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            logger.warning("Config file %s does not contain a dictionary, using defaults", path)
            return Config()
        config = Config(**data)
        # Resolve relative script paths against the project root
        config.build_app.script_path = _resolve_script_path(config.build_app.script_path)
        config.install_app.script_path = _resolve_script_path(config.install_app.script_path)
        return config
    except yaml.YAMLError as e:
        logger.error("Failed to parse config file %s: %s", path, e)
        return Config()
    except IOError as e:
        logger.error("Failed to read config file %s: %s", path, e)
        return Config()
    except Exception as e:
        logger.error("Invalid config in %s: %s", path, e)
        return Config()


def get_config(reload: bool = False) -> Config:
    """Get the globally shared :class:`Config` singleton.

    On first call or when ``reload=True``, reloads from the default path
    (``evalapp.yaml`` in the project root) via :func:`load_config`. Subsequent
    calls reuse the cached instance, avoiding redundant YAML parsing and
    Pydantic validation.
    """
    global _cached_config
    if _cached_config is None or reload:
        _cached_config = load_config()
    return _cached_config


def set_config(cfg: Config) -> None:
    """Inject and replace the global singleton (called by CLI after parsing ``--config``)."""
    global _cached_config
    _cached_config = cfg


def reset_config_cache() -> None:
    """Clear the singleton cache, primarily for use in tests."""
    global _cached_config
    _cached_config = None
