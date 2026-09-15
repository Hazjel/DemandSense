from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import polars as pl
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from demandsense.config import PROJECT_ROOT


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DatasetSpec(StrictModel):
    profile: Literal["release"]
    dataset_version: str
    schema_version: str
    demand_path: Path
    metadata_path: Path
    series_manifest_path: Path
    series_manifest_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")


class FoldSpec(StrictModel):
    fold_id: str
    role: Literal["development", "locked_final_test"]
    train_start: date
    train_end: date
    evaluation_start: date
    evaluation_end: date
    locked: bool

    @model_validator(mode="after")
    def dates_and_lock_are_consistent(self) -> FoldSpec:
        if self.train_start > self.train_end:
            raise ValueError("train_start must not be after train_end")
        if self.evaluation_start != self.train_end + timedelta(days=1):
            raise ValueError("evaluation must begin one day after train_end")
        if self.evaluation_end < self.evaluation_start:
            raise ValueError("evaluation_end must not precede evaluation_start")
        if self.locked != (self.role == "locked_final_test"):
            raise ValueError("only the locked final test may set locked=true")
        return self

    @property
    def evaluation_days(self) -> int:
        return (self.evaluation_end - self.evaluation_start).days + 1


class TemporalSpec(StrictModel):
    horizon_days: int = Field(ge=1)
    minimum_history_days: int = Field(ge=1)
    folds: list[FoldSpec] = Field(min_length=2)


class SegmentSpec(StrictModel):
    definition_version: str
    reference_end_date: date
    usage: Literal["reporting_only"]
    fast_max_zero_ratio: float = Field(ge=0, le=1)
    intermittent_min_zero_ratio: float = Field(ge=0, le=1)


class FeaturePolicy(StrictModel):
    target_features_minimum_lag_days: int = Field(ge=1)
    transforms_fit_scope: Literal["fold_training_only"]
    future_calendar: Literal["allowed_if_known_at_decision_time"]
    future_price: Literal["lagged_only"]
    segment_as_model_feature: Literal[False]
    locked_final_target_access: Literal["after_champion_configuration_freeze"]


class SeasonalNaiveSpec(StrictModel):
    lags: list[int] = Field(min_length=1)
    recursive: Literal[True]


class MetricSpec(StrictModel):
    primary: Literal["weighted_rmsse_store_bottom_level"]
    secondary: list[Literal["mase", "wape", "normalized_bias"]]
    horizon_bands: list[tuple[int, int]]
    zero_denominator_policy: Literal["report_null_and_count"]
    rmsse_scale_start: Literal["first_positive_training_observation"]
    weight_window_days: int = Field(ge=1)


class EvaluationProtocol(StrictModel):
    protocol_version: str
    status: Literal["frozen"]
    dataset: DatasetSpec
    temporal: TemporalSpec
    segments: SegmentSpec
    feature_policy: FeaturePolicy
    seasonal_naive: SeasonalNaiveSpec
    metrics: MetricSpec

    @model_validator(mode="after")
    def protocol_is_internally_consistent(self) -> EvaluationProtocol:
        fold_ids = [fold.fold_id for fold in self.temporal.folds]
        if len(fold_ids) != len(set(fold_ids)):
            raise ValueError("fold_id values must be unique")
        locked = [fold for fold in self.temporal.folds if fold.locked]
        if len(locked) != 1:
            raise ValueError("exactly one locked final fold is required")
        if self.temporal.folds[-1] != locked[0]:
            raise ValueError("locked final fold must be last")
        if any(
            fold.evaluation_days != self.temporal.horizon_days
            for fold in self.temporal.folds
        ):
            raise ValueError("every evaluation window must equal horizon_days")
        if self.segments.fast_max_zero_ratio >= (
            self.segments.intermittent_min_zero_ratio
        ):
            raise ValueError("segment thresholds must be ordered")
        if sorted(set(self.seasonal_naive.lags)) != self.seasonal_naive.lags:
            raise ValueError("seasonal naive lags must be unique and sorted")
        expected_bands = [(1, 7), (8, 14), (15, 21), (22, 28)]
        if self.temporal.horizon_days == 28 and self.metrics.horizon_bands != expected_bands:
            raise ValueError("28-day horizon bands must cover four consecutive weeks")
        return self

    def resolve_paths(self, root: Path = PROJECT_ROOT) -> EvaluationProtocol:
        payload = self.model_dump()
        for key in ("demand_path", "metadata_path", "series_manifest_path"):
            path = Path(payload["dataset"][key])
            payload["dataset"][key] = path if path.is_absolute() else root / path
        return EvaluationProtocol.model_validate(payload)


def load_evaluation_protocol(path: str | Path) -> EvaluationProtocol:
    config_path = Path(path)
    if not config_path.is_absolute():
        config_path = PROJECT_ROOT / config_path
    with config_path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle)
    return EvaluationProtocol.model_validate(payload).resolve_paths()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def validate_evaluation_protocol(protocol: EvaluationProtocol) -> dict[str, Any]:
    metadata = json.loads(protocol.dataset.metadata_path.read_text(encoding="utf-8"))
    manifest = pl.read_parquet(protocol.dataset.series_manifest_path)
    included = manifest.filter(pl.col("included"))
    date_scan = pl.scan_parquet(protocol.dataset.demand_path).select(
        "date", "store_id", "sku_id"
    )
    coverage = date_scan.select(
        pl.col("date").min().alias("min_date"),
        pl.col("date").max().alias("max_date"),
        pl.struct(["store_id", "sku_id"]).n_unique().alias("series_count"),
    ).collect().row(0, named=True)

    folds = protocol.temporal.folds
    locked = next(fold for fold in folds if fold.locked)
    chronological = all(
        earlier.evaluation_end < later.evaluation_start
        and earlier.train_end < later.train_end
        for earlier, later in zip(folds, folds[1:], strict=False)
    )
    contiguous = all(
        earlier.evaluation_end + timedelta(days=1) == later.evaluation_start
        for earlier, later in zip(folds, folds[1:], strict=False)
    )
    history_counts = []
    first_cutoff = folds[0].train_end
    for fold in folds:
        additional_days = (fold.train_end - first_cutoff).days
        short_series = included.filter(
            pl.col("eligibility_history_days") + additional_days
            < protocol.temporal.minimum_history_days
        ).height
        history_counts.append(
            {
                "fold_id": fold.fold_id,
                "cutoff": str(fold.train_end),
                "short_series": short_series,
            }
        )

    segment_dates = manifest["reference_end_date"].unique().to_list()
    checks = {
        "dataset_version_match": (
            metadata["dataset_version"] == protocol.dataset.dataset_version
        ),
        "schema_version_match": (
            metadata["schema_version"] == protocol.dataset.schema_version
        ),
        "metadata_eligibility_cutoff_match": (
            metadata["eligibility_cutoff_date"] == str(folds[0].train_end)
        ),
        "cohort_definition_version_match": (
            metadata["cohort_definition_version"]
            == protocol.segments.definition_version
        ),
        "manifest_checksum_match": (
            _sha256(protocol.dataset.series_manifest_path)
            == protocol.dataset.series_manifest_checksum
        ),
        "selected_series_count_match": included.height == coverage["series_count"],
        "dataset_start_match": coverage["min_date"] == folds[0].train_start,
        "dataset_end_match": coverage["max_date"] == locked.evaluation_end,
        "folds_chronological": chronological,
        "evaluation_windows_contiguous": contiguous,
        "segment_reference_matches_final_cutoff": (
            protocol.segments.reference_end_date == locked.train_end
        ),
        "manifest_segment_reference_match": segment_dates
        == [protocol.segments.reference_end_date],
        "manifest_eligibility_cutoff_match": (
            manifest["eligibility_cutoff_date"].unique().to_list()
            == [folds[0].train_end]
        ),
        "minimum_history_satisfied": all(
            item["short_series"] == 0 for item in history_counts
        ),
        "final_targets_excluded_from_development": all(
            fold.evaluation_end < locked.evaluation_start
            for fold in folds
            if fold.role == "development"
        ),
        "segment_not_used_as_model_feature": (
            protocol.segments.usage == "reporting_only"
            and not protocol.feature_policy.segment_as_model_feature
        ),
        "target_features_are_lagged": (
            protocol.feature_policy.target_features_minimum_lag_days >= 1
        ),
        "transforms_fit_per_fold": (
            protocol.feature_policy.transforms_fit_scope == "fold_training_only"
        ),
        "future_price_is_lagged": protocol.feature_policy.future_price == "lagged_only",
        "seasonal_naive_is_recursive": protocol.seasonal_naive.recursive,
    }
    status = "passed" if all(checks.values()) else "failed"
    return {
        "status": status,
        "protocol_version": protocol.protocol_version,
        "dataset_version": protocol.dataset.dataset_version,
        "validated_at": datetime.now(UTC).isoformat(),
        "dataset_coverage": {
            "min_date": str(coverage["min_date"]),
            "max_date": str(coverage["max_date"]),
            "series_count": coverage["series_count"],
        },
        "fold_history_checks": history_counts,
        "checks": checks,
        "target_columns_read": [],
        "final_target_values_accessed": False,
    }


def freeze_evaluation_protocol(
    config_path: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    protocol = load_evaluation_protocol(config_path)
    report = validate_evaluation_protocol(protocol)
    if report["status"] != "passed":
        raise ValueError(f"Evaluation protocol validation failed: {report}")

    destination = Path(output_dir)
    if not destination.is_absolute():
        destination = PROJECT_ROOT / destination
    destination.mkdir(parents=True, exist_ok=True)

    fold_frame = pl.DataFrame(
        [
            {
                **fold.model_dump(mode="python"),
                "horizon_days": fold.evaluation_days,
                "protocol_version": protocol.protocol_version,
                "dataset_version": protocol.dataset.dataset_version,
            }
            for fold in protocol.temporal.folds
        ]
    )
    folds_path = destination / "temporal_folds.parquet"
    fold_frame.write_parquet(folds_path, compression="zstd", statistics=True)

    report_path = destination / "leakage_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    protocol_path = destination / "evaluation_protocol.json"
    protocol_path.write_text(
        json.dumps(protocol.model_dump(mode="json"), indent=2), encoding="utf-8"
    )
    freeze_manifest = {
        "status": "frozen",
        "protocol_version": protocol.protocol_version,
        "dataset_version": protocol.dataset.dataset_version,
        "frozen_at": datetime.now(UTC).isoformat(),
        "protocol_checksum": _sha256(protocol_path),
        "temporal_folds_checksum": _sha256(folds_path),
        "leakage_report_checksum": _sha256(report_path),
        "series_manifest_checksum": protocol.dataset.series_manifest_checksum,
    }
    freeze_manifest_path = destination / "freeze_manifest.json"
    freeze_manifest_path.write_text(
        json.dumps(freeze_manifest, indent=2), encoding="utf-8"
    )
    return {
        "status": "frozen",
        "protocol_path": str(protocol_path),
        "folds_path": str(folds_path),
        "leakage_report_path": str(report_path),
        "freeze_manifest_path": str(freeze_manifest_path),
        "protocol_version": protocol.protocol_version,
        "dataset_version": protocol.dataset.dataset_version,
        "checks": report["checks"],
    }
