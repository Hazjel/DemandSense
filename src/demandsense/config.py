from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PathsConfig(StrictModel):
    raw_dir: Path
    interim_dir: Path
    processed_dir: Path
    artifact_dir: Path


class DataConfig(StrictModel):
    source: Literal["m5"] = "m5"
    competition: str = "m5-forecasting-accuracy"
    store_id: str = "CA_1"
    profile: Literal["smoke", "development", "release"] = "development"
    series_limit: int | None = Field(default=300, ge=1)
    selection_seed: int = 42

    @model_validator(mode="after")
    def release_has_no_limit(self) -> DataConfig:
        if self.profile == "release" and self.series_limit is not None:
            raise ValueError("release profile must use every eligible series (series_limit: null)")
        return self


class ForecastConfig(StrictModel):
    horizon: int = Field(default=28, ge=1)
    minimum_history_days: int = Field(default=112, ge=56)
    development_folds: int = Field(default=3, ge=0)


class SegmentationConfig(StrictModel):
    fast_max_zero_ratio: float = Field(default=0.20, ge=0, le=1)
    intermittent_min_zero_ratio: float = Field(default=0.60, ge=0, le=1)

    @model_validator(mode="after")
    def thresholds_are_ordered(self) -> SegmentationConfig:
        if self.fast_max_zero_ratio >= self.intermittent_min_zero_ratio:
            raise ValueError("fast threshold must be below intermittent threshold")
        return self


class ValidationConfig(StrictModel):
    global_missing_price_warning_ratio: float = Field(default=0.25, ge=0, le=1)
    series_missing_price_warning_ratio: float = Field(default=0.75, ge=0, le=1)
    long_zero_run_warning_days: int = Field(default=84, ge=1)
    inactive_tail_warning_days: int = Field(default=84, ge=1)
    extreme_quantity_quantile: float = Field(default=0.999, gt=0, lt=1)
    extreme_price_change_ratio: float = Field(default=1.0, gt=0)


class ModelsConfig(StrictModel):
    global_model: Literal["xgboost"] = "xgboost"
    xgboost_device: Literal["cpu", "cuda"] = "cuda"
    foundation_model: str = "amazon/chronos-bolt-small"
    foundation_batch_size: int = Field(default=8, ge=1)


class RuntimeConfig(StrictModel):
    random_seed: int = 42
    n_jobs: int = Field(default=8, ge=1)


class ProjectConfig(StrictModel):
    paths: PathsConfig
    data: DataConfig
    forecast: ForecastConfig
    segmentation: SegmentationConfig
    validation: ValidationConfig
    models: ModelsConfig
    runtime: RuntimeConfig

    def resolve_paths(self, root: Path = PROJECT_ROOT) -> ProjectConfig:
        payload = self.model_dump()
        for key, value in payload["paths"].items():
            path = Path(value)
            payload["paths"][key] = path if path.is_absolute() else root / path
        return ProjectConfig.model_validate(payload)


def _deep_merge(base: dict, override: dict) -> dict:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(config_path: str | Path) -> ProjectConfig:
    path = Path(config_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    if not path.exists():
        raise FileNotFoundError(f"Configuration not found: {path}")

    base_path = PROJECT_ROOT / "configs" / "base.yaml"
    with base_path.open("r", encoding="utf-8") as handle:
        base = yaml.safe_load(handle) or {}
    with path.open("r", encoding="utf-8") as handle:
        override = yaml.safe_load(handle) or {}

    payload = base if path.resolve() == base_path.resolve() else _deep_merge(base, override)
    return ProjectConfig.model_validate(payload).resolve_paths()
