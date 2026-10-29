"""Standalone configuration; no evalapp installation is required."""
from pathlib import Path
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .scoring_config import ScoringSettings

class ModelConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = 'qwen3.8-flash'
    base_url: str = ''
    api_key: str = Field(default='', repr=False, exclude=True)
    api_key_env: str = 'QUICKCHECK_API_KEY'
    request_options: dict = Field(default_factory=dict)


class WebSettings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    host: str = '127.0.0.1'
    port: int = Field(8766, ge=0, le=65535)
    workers: int = Field(5, ge=1, le=8)
    max_queued: int = Field(4, ge=0, le=100)
    share_host: str | None = None
    share_port: int | None = Field(None, ge=1, le=65535)

class Settings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    scoring: ScoringSettings = Field(default_factory=ScoringSettings)
    model: ModelConfig = Field(default_factory=ModelConfig)
    web: WebSettings = Field(default_factory=WebSettings)
    model_concurrency: int = Field(5, ge=1, le=8)
    browser_channel: str | None = None
    deadline_seconds: float = Field(120, ge=5, le=3600)
    cleanup_seconds: float = Field(2, gt=0, le=3)
    navigation_seconds: float = Field(10, gt=0)
    screenshot_seconds: float = Field(3, gt=0)
    blank_pixel_stddev: float = Field(1.5, ge=0)
    overflow_tolerance_pixels: int = Field(4, ge=0)
    readiness_seconds: float = Field(8, ge=1, le=30)
    minimum_observation_seconds: float = Field(4, ge=0)
    sample_interval_seconds: float = Field(1, gt=0)
    stable_samples: int = Field(2, ge=2, le=10)
    layout_tolerance_pixels: int = Field(3, ge=0)
    frame_change_threshold: float = Field(.015, ge=0, le=1)
    phash_distance: int = Field(6, ge=0, le=63)
    dedup_pixel_threshold: float = Field(.008, ge=0, le=1)
    dedup_local_threshold: float = Field(.015, ge=0, le=1)
    observation_seconds: float = Field(2, ge=0)
    model_seconds: float = Field(120, gt=0)
    model_max_retries: int = Field(2, ge=0, le=4)
    model_retry_backoff_seconds: float = Field(1, ge=0, le=10)
    viewports: dict[str, dict[str, int]] = Field(default_factory=lambda: {
        'mobile': {'width': 390, 'height': 844}, 'desktop': {'width': 1440, 'height': 900}})

    @model_validator(mode='after')
    def validate_capture(self):
        if self.minimum_observation_seconds > self.readiness_seconds:
            raise ValueError('minimum observation must fit readiness budget')
        if set(self.viewports) != {'mobile', 'desktop'}:
            raise ValueError('mobile and desktop viewports are required')
        for viewport in self.viewports.values():
            if set(viewport) != {'width', 'height'} or any(not 0 < value <= 4096 for value in viewport.values()):
                raise ValueError('viewport requires width and height between 1 and 4096')
        return self

class ApplicationConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    workspace_root: str = '~/eval_app_factory'
    quickcheck: Settings = Field(default_factory=Settings)

    @property
    def output_dir(self) -> Path:
        return Path(self.workspace_root).expanduser() / 'quickcheck'

def load_config(path=None) -> ApplicationConfig:
    candidate = Path(path) if path is not None else Path.cwd() / 'quickcheck.yaml'
    if not candidate.exists() and path is None:
        return ApplicationConfig()
    with candidate.open(encoding='utf-8') as stream:
        data = yaml.safe_load(stream) or {}
    return ApplicationConfig.model_validate(data)
