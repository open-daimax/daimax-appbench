"""Data models for test cases."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

# 统一优先级格式: P0(最高)/P1/P2(最低)
TestCasePriority = Literal["P0", "P1", "P2"]

# Legacy priority 到新格式的映射
_PRIORITY_NORMALIZE_MAP = {
    "high": "P0",
    "medium": "P1",
    "low": "P2",
    "p0": "P0",
    "p1": "P1",
    "p2": "P2",
}


class TestCase(BaseModel):
    """A single test case for evaluating a generated app."""
    id: str
    name: str
    description: str
    steps: list[str] = Field(default_factory=list)
    expected_result: str = ""
    priority: TestCasePriority = "P1"
    category: str = ""  # 用例分类 (如 "launch_check", "core_function", "ui_interaction")

    @field_validator("priority", mode="before")
    @classmethod
    def _normalize_priority(cls, v: str) -> str:
        """Normalize legacy priority values (high/medium/low) to P0/P1/P2."""
        if isinstance(v, str):
            normalized = _PRIORITY_NORMALIZE_MAP.get(v.lower())
            if normalized:
                return normalized
        return v


class TestDesignOutput(BaseModel):
    """Output from the test-design step."""
    prompt_id: str
    platform: str
    test_cases: list[TestCase] = Field(default_factory=list)
    raw_output: str = ""
