"""Resolve an explicitly chosen aesthetics model without provider defaults."""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

from .aesthetics_scorer import ModelConfig

if TYPE_CHECKING:
    from ....config import ModelEndpointConfig


def resolve_model_config(
    endpoint: ModelEndpointConfig | None = None,
    model_name: str | None = None,
) -> ModelConfig:
    """Prefer explicit fields over environment values; leave missing fields empty.

    ``DASHSCOPE_API_KEY`` remains a compatibility fallback for credentials only;
    its presence never selects a provider endpoint or model. API keys are optional
    for explicitly configured local services that do not require authentication.
    """
    return ModelConfig(
        base_url=((endpoint.base_url if endpoint else '')
                  or os.environ.get('AESTHETICS_BASE_URL', '')).strip(),
        name=(model_name or (endpoint.name if endpoint else '')
              or os.environ.get('AESTHETICS_MODEL', '')).strip(),
        api_key=(endpoint.api_key if endpoint else '')
        or os.environ.get('AESTHETICS_API_KEY', '')
        or os.environ.get('DASHSCOPE_API_KEY', ''),
    )
