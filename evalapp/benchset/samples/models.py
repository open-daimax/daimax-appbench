"""Data models for benchmark evaluation samples."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator


class EvalPrompt(BaseModel):
    """A prompt used to evaluate an app generator."""
    id: str
    text: str
    title: str = ""  # 中文标题 (来自 EvalSample.title)
    category: str = "general"
    platforms: list[str] = Field(default_factory=lambda: ["ios", "android"])
    difficulty: str = "medium"
    expected_features: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)  # 约束条件 (来自 EvalSample.constraints)
    notes: str = ""  # 补充说明 (来自 EvalSample.notes)
    game_category: str = ""  # 游戏分类 (来自 EvalSample.game_category)
    requires_backend: bool = False  # Whether the sample requires backend services
    requires_auth: bool = False  # Whether the sample requires user authentication (login/register)


class EvalSample(BaseModel):
    """A benchmark sample loaded from dataset."""

    sample_id: str
    title: str = ""  # Display name (e.g., "开心消消乐")
    requirement: str
    platforms: list[str] = Field(
        default_factory=lambda: ["android"],
        deprecated="Use execution_plan in index.yaml for platform targeting. "
                   "Retained only for backward compatibility with get_tasks() fallback.",
    )
    app_type: str = "general"
    game_category: str = ""  # Game category (e.g., "消除类", "跑酷类")
    complexity: str = "medium"  # 样本复杂度 (low/medium/high)
    top_category: str = ""  # TOP应用分类 (如 "游戏", "工具", "社交")
    core_functions: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    notes: str = ""

    @field_validator("core_functions", "constraints", mode="before")
    @classmethod
    def _coerce_str_to_list(cls, value):
        """兼容 YAML 中以块标量(字符串)形式书写的列表字段，将字符串转为单元素列表。"""
        if value is None:
            return []
        if isinstance(value, str):
            text = value.strip()
            return [text] if text else []
        return value
    requires_backend: bool = False  # Whether the sample requires backend services
    requires_auth: bool = False  # Whether the sample requires user authentication (login/register)

    # V2 版本管理字段
    dataset_version: str = "v1"  # 样本集版本，v1=旧版/废弃, v2=新版
    status: str = "active"  # active/deprecated
    deprecated_reason: Optional[str] = None  # 废弃原因
    pages: list = Field(default_factory=list)  # V2 页面结构列表
    mock_resources: dict = Field(default_factory=dict)  # 媒体资源URL配置

    def to_eval_prompt(self) -> EvalPrompt:
        """Adapt a sample into the existing test design input model."""
        return EvalPrompt(
            id=self.sample_id,
            text=self.requirement,
            title=self.title,
            category=self.app_type,
            platforms=self.platforms,
            difficulty="medium",  # Default difficulty
            expected_features=self.core_functions,
            constraints=self.constraints,
            notes=self.notes,
            game_category=self.game_category,
            requires_backend=self.requires_backend,
            requires_auth=self.requires_auth,
        )
