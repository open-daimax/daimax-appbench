"""Abstract generator interface and plugin registry (evaluation-side contract).

The evaluation framework itself does not contain any app generator implementation:
generator capabilities are provided as plugins by separate repositories
(e.g., daimax-appbench-gen / evalgen). A plugin package only needs to:

1. Subclass :class:`AppGenerator` from this module and declare a non-empty
   ``name`` class attribute; the subclass will be automatically registered
   in :class:`GeneratorRegistry` via the ``__init_subclass__`` hook.
2. Declare an entry point group ``evalapp.generators`` in its own
   ``pyproject.toml``, for example::

       [project.entry-points."evalapp.generators"]
       my_gen = "my_pkg.generators:MyGenerator"

:func:`get_generator` automatically loads this entry point group when
the registry misses (no manual imports needed after ``pip install``).
"""

from __future__ import annotations

import importlib.metadata as _importlib_metadata
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

ENTRY_POINT_GROUP = "evalapp.generators"


@dataclass
class GenerationResult:
    """Result from generating an app."""
    success: bool
    session_id: str = ""
    project_path: str = ""
    project_id: str = ""
    platform: str = ""
    duration: float = 0.0
    error: str | None = None
    generator_name: str = ""
    h5_url: str = ""
    metadata: dict = field(default_factory=dict)


class GeneratorRegistry:
    """Automatic generator registry.

    Each :class:`AppGenerator` subclass is automatically registered here
    via the ``__init_subclass__`` hook when loaded by Python, making it
    discoverable by :func:`get_generator`. Usage: declare a class attribute
    ``name = "mygen"`` (non-empty string) on the subclass.
    Abstract intermediate classes with empty ``name`` are not registered.
    """

    _registry: dict[str, type["AppGenerator"]] = {}

    @classmethod
    def register(cls, generator_cls: type["AppGenerator"]) -> type["AppGenerator"]:
        """Register a generator class in the global registry.

        Can be used as a decorator; also called internally by ``__init_subclass__``.
        Raises an error on duplicate name registration to avoid silent overwrites.
        """
        name = getattr(generator_cls, "name", "") or ""
        if not isinstance(name, str) or not name:
            return generator_cls
        existing = cls._registry.get(name)
        if existing is not None and existing is not generator_cls:
            raise ValueError(
                f"Generator name {name!r} 已被 {existing.__name__} 注册，"
                f"不能重复使用于 {generator_cls.__name__}"
            )
        cls._registry[name] = generator_cls
        return generator_cls

    @classmethod
    def get(cls, name: str) -> type["AppGenerator"] | None:
        """Look up a registered generator class by name."""
        return cls._registry.get(name)

    @classmethod
    def names(cls) -> list[str]:
        """Return all currently registered generator names."""
        return sorted(cls._registry.keys())

    @classmethod
    def all(cls) -> dict[str, type["AppGenerator"]]:
        """Return a shallow copy of the registry."""
        return dict(cls._registry)


class AppGenerator(ABC):
    """Abstract interface for app generators."""

    # 子类通过覆写该类属性声明生成器名称（作为注册表 key）。
    name: str = ""

    # 生成器声明支持的平台列表，子类可覆写。
    supported_platforms: list[str] = []

    def __init_subclass__(cls, **kwargs) -> None:
        """Automatically register subclasses in :class:`GeneratorRegistry`.

        Only registers when the subclass explicitly sets a non-empty ``name``
        class attribute, to avoid registering abstract intermediate base classes.
        """
        super().__init_subclass__(**kwargs)
        name = cls.__dict__.get("name", "")
        if isinstance(name, str) and name:
            GeneratorRegistry.register(cls)

    # ── Optional lifecycle hooks ──────────────────────────────────────
    def setup(self) -> None:
        """Initialize resources needed by the generator. Default no-op."""
        pass

    def teardown(self) -> None:
        """Release resources acquired during setup(). Default no-op."""
        pass

    def validate_config(self) -> None:
        """Validate the generator configuration. Default no-op."""
        pass

    @abstractmethod
    def generate(
        self,
        prompt_text: str,
        platform: str,
        session_id: str | None = None,
        workspace_dir: str | None = None,
        constraints: list[str] | None = None,
    ) -> GenerationResult:
        """Generate an app from the given prompt.

        Args:
            prompt_text: Natural language description of the app.
            platform: Target platform ("ios" or "android").
            session_id: Optional caller-specified session identifier used to
                correlate generator-side process data.
            workspace_dir: Optional workspace directory for generated project.
                If provided, generators should use this directory instead of
                their default workspace.
            constraints: Optional list of constraint strings to append to the
                prompt as a "## Constraints" section.

        Returns:
            GenerationResult with generation outcome.
        """
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this generator is available on the system."""
        ...

    def resume(
        self,
        prompt_text: str,
        session_id: str,
        workspace_dir: str | None = None,
    ) -> GenerationResult:
        """Resume generation with additional requirements.

        Default implementation raises NotImplementedError.
        Subclasses should override if they support resume functionality.
        """
        raise NotImplementedError(
            f"Generator '{self.name}' does not support resume functionality"
        )


def _load_entry_point_generators() -> None:
    """加载通过 entry point 组 ``evalapp.generators`` 声明的生成器插件。

    导入插件模块即可触发其子类的 ``__init_subclass__`` 自动注册；
    加载失败的插件仅记录 warning，不影响其余生成器。
    """
    try:
        eps = _importlib_metadata.entry_points(group=ENTRY_POINT_GROUP)
    except Exception:
        return
    for ep in eps:
        try:
            ep.load()
        except Exception as e:  # noqa: BLE001 - 插件加载失败不应中断评测
            import logging

            logging.getLogger(__name__).warning(
                "加载生成器插件 %s 失败: %s", ep.name, e
            )


def get_generator(name: str, config) -> AppGenerator:
    """Look up and instantiate a generator by name.

    First searches the in-process registry; on miss, loads the entry point
    group ``evalapp.generators`` and retries. Raises ``ValueError`` with
    installation guidance if still not found.
    """
    cls = GeneratorRegistry.get(name)
    if cls is None:
        _load_entry_point_generators()
        cls = GeneratorRegistry.get(name)
    if cls is None:
        available = GeneratorRegistry.names()
        hint = (
            f"Unknown generator: {name!r}. "
            f"Available: {available if available else '(none)'}。"
            "评测仓本身不内置生成器，请安装生成插件包（如 daimax-appbench-gen）"
            f"并在其 pyproject 中声明 entry point 组 {ENTRY_POINT_GROUP!r}。"
        )
        raise ValueError(hint)
    return cls(config)


class ExternalArtifactGenerator(AppGenerator):
    """Built-in placeholder generator for direct artifact evaluation.

    When using ``evalapp evaluate --url/--apk/--app/--project`` (direct artifact
    evaluation mode), the application under test already exists and no generation
    is needed. This class merely serves as a generator placeholder for the
    evaluation pipeline, allowing the open-source version to evaluate artifacts
    without installing a generator plugin.
    """

    name = "external"
    supported_platforms = ["web", "android", "ios", "h5", "miniprogram"]

    def __init__(self, config=None) -> None:
        self.config = config

    def generate(self, prompt_text, platform, session_id=None,
                 workspace_dir=None, constraints=None) -> GenerationResult:
        return GenerationResult(
            success=False,
            platform=platform,
            generator_name=self.name,
            error="external 生成器仅用于产物直评（--url/--apk/--app/--project），不支持代码生成",
        )

    def is_available(self) -> bool:
        return True


__all__ = [
    "ENTRY_POINT_GROUP",
    "AppGenerator",
    "ExternalArtifactGenerator",
    "GenerationResult",
    "GeneratorRegistry",
    "get_generator",
]
