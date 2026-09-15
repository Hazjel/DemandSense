from __future__ import annotations

import hashlib
import json
import time
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import polars as pl
import yaml
from pydantic import BaseModel, ConfigDict, Field

from demandsense.config import PROJECT_ROOT
from demandsense.evaluation.baselines import croston_sba, seasonal_naive
from demandsense.evaluation.metrics import forecast_metrics, scaling_denominators
from demandsense.evaluation.protocol import (
    EvaluationProtocol,
    FoldSpec,
    load_evaluation_protocol,
    validate_evaluation_protocol,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CrostonSpec(StrictModel):
    variant: Literal["sba"]
    alpha: float = Field(gt=0, le=1)


class BaselineSuiteSpec(StrictModel):
    suite_version: str
    protocol_path: Path
    fold_scope: Literal["development_only"]
    locked_final_target_access: Literal[False]
    croston: CrostonSpec

    def resolve_paths(self, root: Path = PROJECT_ROOT) -> BaselineSuiteSpec:
        payload = self.model_dump()
        protocol_path = Path(payload["protocol_path"])
        payload["protocol_path"] = (
            protocol_path if protocol_path.is_absolute() else root / protocol_path
        )
        return BaselineSuiteSpec.model_validate(payload)


def load_baseline_suite(path: str | Path) -> BaselineSuiteSpec:
    config_path = Path(path)
    if not config_path.is_absolute():
        config_path = PROJECT_ROOT / config_path
    with config_path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle)
    return BaselineSuiteSpec.model_validate(payload).resolve_paths()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_identifier(payload: dict[str, Any], prefix: str) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=str
    ).encode()
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:12]}"


def _model_specs(
    protocol: EvaluationProtocol, suite: BaselineSuiteSpec
) -> list[dict[str, Any]]:
    models = []
    for lag in protocol.seasonal_naive.lags:
        models.append(
            {
                "model_id": "naive_last" if lag == 1 else f"seasonal_naive_lag_{lag}",
                "family": "naive" if lag == 1 else "seasonal_naive",
                "lag": lag,
            }
        )
    models.append(
        {
            "model_id": "croston_sba",
            "family": "intermittent",
            "alpha": suite.croston.alpha,
        }
    )
    return models


def _fold_frame(
    protocol: EvaluationProtocol,
    fold: FoldSpec,
    manifest: pl.DataFrame,
) -> pl.DataFrame:
    weight_start = fold.train_end - timedelta(
        days=protocol.metrics.weight_window_days - 1
    )
    demand = (
        pl.scan_parquet(protocol.dataset.demand_path)
        .filter(pl.col("date") <= fold.evaluation_end)
        .select("date", "store_id", "sku_id", "quantity_sold", "unit_price")
    )
    history_filter = pl.col("date") <= fold.train_end
    evaluation_filter = pl.col("date").is_between(
        fold.evaluation_start, fold.evaluation_end, closed="both"
    )
    weight_filter = pl.col("date").is_between(
        weight_start, fold.train_end, closed="both"
    )
    grouped = (
        demand.group_by("store_id", "sku_id")
        .agg(
            pl.col("quantity_sold")
            .filter(history_filter)
            .sort_by(pl.col("date").filter(history_filter))
            .alias("history"),
            pl.col("quantity_sold")
            .filter(evaluation_filter)
            .sort_by(pl.col("date").filter(evaluation_filter))
            .alias("actual"),
            (
                pl.col("quantity_sold")
                * pl.col("unit_price").fill_null(0.0)
            )
            .filter(weight_filter)
            .sum()
            .alias("weight_revenue"),
        )
        .collect(engine="streaming")
        .join(
            manifest.filter(pl.col("included")).select(
                "store_id", "sku_id", "segment", "active_start_date"
            ),
            on=["store_id", "sku_id"],
            how="inner",
        )
        .sort("store_id", "sku_id")
    )
    expected_series = manifest.filter(pl.col("included")).height
    if grouped.height != expected_series:
        raise ValueError(
            f"{fold.fold_id} contains {grouped.height} series; expected {expected_series}"
        )
    invalid_lengths = grouped.filter(
        (pl.col("history").list.len() < protocol.temporal.minimum_history_days)
        | (pl.col("actual").list.len() != protocol.temporal.horizon_days)
    ).height
    if invalid_lengths:
        raise ValueError(
            f"{fold.fold_id} contains {invalid_lengths} invalid history/evaluation lengths"
        )
    return grouped


def _aggregate_metrics(
    records: list[dict[str, Any]],
) -> pl.DataFrame:
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        base = (record["fold_id"], record["model_id"])
        groups[(*base, "all", record["horizon_band"])].append(record)
        groups[(*base, record["segment"], record["horizon_band"])].append(record)

    aggregates = []
    for (fold_id, model_id, segment, horizon_band), rows in sorted(groups.items()):
        rmsse_rows = [row for row in rows if row["rmsse"] is not None]
        mase_values = [row["mase"] for row in rows if row["mase"] is not None]
        total_revenue = sum(row["weight_revenue"] for row in rows)
        valid_revenue = sum(row["weight_revenue"] for row in rmsse_rows)
        actual_sum = sum(row["actual_sum"] for row in rows)
        absolute_error_sum = sum(row["absolute_error_sum"] for row in rows)
        error_sum = sum(row["error_sum"] for row in rows)
        weighted_rmsse = (
            sum(row["rmsse"] * row["weight_revenue"] for row in rmsse_rows)
            / valid_revenue
            if valid_revenue > 0
            else None
        )
        aggregates.append(
            {
                "fold_id": fold_id,
                "model_id": model_id,
                "segment": segment,
                "horizon_band": horizon_band,
                "horizon_start": rows[0]["horizon_start"],
                "horizon_end": rows[0]["horizon_end"],
                "series_count": len(rows),
                "rmsse_valid_count": len(rmsse_rows),
                "rmsse_invalid_count": len(rows) - len(rmsse_rows),
                "mase_valid_count": len(mase_values),
                "zero_actual_series_count": sum(
                    row["actual_sum"] == 0 for row in rows
                ),
                "weight_revenue": total_revenue,
                "weight_coverage": (
                    valid_revenue / total_revenue if total_revenue > 0 else None
                ),
                "weighted_rmsse_store_bottom_level": weighted_rmsse,
                "mase_mean": (
                    sum(mase_values) / len(mase_values) if mase_values else None
                ),
                "wape": (
                    absolute_error_sum / actual_sum if actual_sum > 0 else None
                ),
                "normalized_bias": error_sum / actual_sum if actual_sum > 0 else None,
            }
        )
    return pl.DataFrame(aggregates).sort(
        "fold_id", "model_id", "segment", "horizon_start"
    )


def _model_summary(aggregate: pl.DataFrame) -> dict[str, Any]:
    overall = aggregate.filter(
        (pl.col("segment") == "all") & (pl.col("horizon_band") == "all")
    )
    ranking = (
        overall.group_by("model_id")
        .agg(
            pl.col("weighted_rmsse_store_bottom_level")
            .mean()
            .alias("mean_weighted_rmsse"),
            pl.col("weighted_rmsse_store_bottom_level")
            .std(ddof=0)
            .alias("std_weighted_rmsse"),
            pl.col("mase_mean").mean().alias("mean_mase"),
            pl.col("wape").mean().alias("mean_wape"),
            pl.col("normalized_bias").mean().alias("mean_normalized_bias"),
            pl.len().alias("fold_count"),
        )
        .sort("mean_weighted_rmsse", "model_id")
        .with_row_index("baseline_rank", offset=1)
    )
    fold_scores = overall.sort("fold_id", "model_id").to_dicts()
    return {
        "selection_scope": "development_folds_only",
        "selection_metric": "mean_weighted_rmsse",
        "best_baseline_model_id": ranking["model_id"][0],
        "ranking": ranking.to_dicts(),
        "fold_scores": fold_scores,
    }


def run_baseline_suite(
    config_path: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    started = time.perf_counter()
    suite = load_baseline_suite(config_path)
    protocol = load_evaluation_protocol(suite.protocol_path)
    validation = validate_evaluation_protocol(protocol)
    if validation["status"] != "passed":
        raise ValueError(f"Evaluation protocol validation failed: {validation}")

    folds = [fold for fold in protocol.temporal.folds if fold.role == "development"]
    if not folds or any(fold.locked for fold in folds):
        raise ValueError("baseline suite requires unlocked development folds")
    manifest = pl.read_parquet(protocol.dataset.series_manifest_path)
    models = _model_specs(protocol, suite)
    identity = {
        "suite_version": suite.suite_version,
        "fold_scope": suite.fold_scope,
        "locked_final_target_access": suite.locked_final_target_access,
        "croston": suite.croston.model_dump(mode="json"),
        "protocol_version": protocol.protocol_version,
        "dataset_version": protocol.dataset.dataset_version,
        "series_manifest_checksum": protocol.dataset.series_manifest_checksum,
        "temporal": protocol.temporal.model_dump(mode="json"),
        "segments": protocol.segments.model_dump(mode="json"),
        "feature_policy": protocol.feature_policy.model_dump(mode="json"),
        "seasonal_naive": protocol.seasonal_naive.model_dump(mode="json"),
        "metrics": protocol.metrics.model_dump(mode="json"),
        "models": models,
    }
    run_id = _stable_identifier(identity, "baseline")

    prediction_records: list[dict[str, Any]] = []
    metric_records: list[dict[str, Any]] = []
    for fold in folds:
        frame = _fold_frame(protocol, fold, manifest)
        for row in frame.iter_rows(named=True):
            history = row["history"]
            actual = row["actual"]
            rmsse_scale, mase_scale = scaling_denominators(history)
            for model in models:
                if model["model_id"] == "croston_sba":
                    active_offset = max(
                        0, (row["active_start_date"] - fold.train_start).days
                    )
                    forecast = croston_sba(
                        history[active_offset:],
                        protocol.temporal.horizon_days,
                        alpha=suite.croston.alpha,
                    )
                else:
                    forecast = seasonal_naive(
                        history,
                        protocol.temporal.horizon_days,
                        lag=model["lag"],
                    )
                for horizon_index, (predicted, observed) in enumerate(
                    zip(forecast, actual, strict=True), start=1
                ):
                    prediction_records.append(
                        {
                            "run_id": run_id,
                            "protocol_version": protocol.protocol_version,
                            "dataset_version": protocol.dataset.dataset_version,
                            "fold_id": fold.fold_id,
                            "model_id": model["model_id"],
                            "store_id": row["store_id"],
                            "sku_id": row["sku_id"],
                            "segment": row["segment"],
                            "cutoff_date": fold.train_end,
                            "forecast_date": fold.evaluation_start
                            + timedelta(days=horizon_index - 1),
                            "horizon": horizon_index,
                            "prediction": max(0.0, predicted),
                            "actual": observed,
                        }
                    )
                bands = [("all", 1, protocol.temporal.horizon_days)] + [
                    (f"days_{start:02d}_{end:02d}", start, end)
                    for start, end in protocol.metrics.horizon_bands
                ]
                for band_name, band_start, band_end in bands:
                    metrics = forecast_metrics(
                        actual[band_start - 1 : band_end],
                        forecast[band_start - 1 : band_end],
                        rmsse_scale,
                        mase_scale,
                    )
                    metric_records.append(
                        {
                            "run_id": run_id,
                            "fold_id": fold.fold_id,
                            "model_id": model["model_id"],
                            "store_id": row["store_id"],
                            "sku_id": row["sku_id"],
                            "segment": row["segment"],
                            "horizon_band": band_name,
                            "horizon_start": band_start,
                            "horizon_end": band_end,
                            "weight_revenue": row["weight_revenue"],
                            **metrics,
                        }
                    )

    predictions = pl.DataFrame(prediction_records).sort(
        "fold_id", "model_id", "store_id", "sku_id", "horizon"
    )
    per_series = pl.DataFrame(metric_records).sort(
        "fold_id", "model_id", "store_id", "sku_id", "horizon_start"
    )
    aggregate = _aggregate_metrics(metric_records)
    summary = _model_summary(aggregate)

    destination = Path(output_dir)
    if not destination.is_absolute():
        destination = PROJECT_ROOT / destination
    destination.mkdir(parents=True, exist_ok=True)
    artifact_frames = {
        "predictions": predictions,
        "per_series_metrics": per_series,
        "aggregate_metrics": aggregate,
    }
    artifact_paths: dict[str, Path] = {}
    for name, frame in artifact_frames.items():
        artifact_path = destination / f"{name}.parquet"
        frame.write_parquet(artifact_path, compression="zstd", statistics=True)
        artifact_paths[name] = artifact_path

    summary_path = destination / "model_summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    artifact_paths["model_summary"] = summary_path
    checksums = {name: _sha256(path) for name, path in artifact_paths.items()}
    result_manifest = {
        "status": "complete",
        "run_id": run_id,
        "suite_version": suite.suite_version,
        "protocol_version": protocol.protocol_version,
        "dataset_version": protocol.dataset.dataset_version,
        "fold_ids": [fold.fold_id for fold in folds],
        "model_ids": [model["model_id"] for model in models],
        "series_count": manifest.filter(pl.col("included")).height,
        "prediction_row_count": predictions.height,
        "per_series_metric_row_count": per_series.height,
        "aggregate_metric_row_count": aggregate.height,
        "maximum_target_date_accessed": str(max(fold.evaluation_end for fold in folds)),
        "locked_final_target_accessed": False,
        "artifact_checksums": checksums,
    }
    result_manifest_path = destination / "result_manifest.json"
    result_manifest_path.write_text(
        json.dumps(result_manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    metadata = {
        **result_manifest,
        "created_at": datetime.now(UTC).isoformat(),
        "runtime_seconds": time.perf_counter() - started,
        "result_manifest_checksum": _sha256(result_manifest_path),
    }
    metadata_path = destination / "run_metadata.json"
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8"
    )
    return {
        **result_manifest,
        "output_dir": str(destination),
        "best_baseline_model_id": summary["best_baseline_model_id"],
        "ranking": summary["ranking"],
        "runtime_seconds": metadata["runtime_seconds"],
        "result_manifest_checksum": metadata["result_manifest_checksum"],
    }


def verify_baseline_reproducibility(
    config_path: str | Path,
    reference_dir: str | Path,
    reproduction_dir: str | Path,
) -> dict[str, Any]:
    reference = Path(reference_dir)
    if not reference.is_absolute():
        reference = PROJECT_ROOT / reference
    reference_manifest_path = reference / "result_manifest.json"
    if not reference_manifest_path.exists():
        raise FileNotFoundError(f"Reference manifest not found: {reference_manifest_path}")
    expected = json.loads(reference_manifest_path.read_text(encoding="utf-8"))
    actual_run = run_baseline_suite(config_path, reproduction_dir)
    candidate = Path(actual_run["output_dir"]) / "result_manifest.json"
    actual = json.loads(candidate.read_text(encoding="utf-8"))
    checks = {
        "run_id_match": expected["run_id"] == actual["run_id"],
        "fold_ids_match": expected["fold_ids"] == actual["fold_ids"],
        "model_ids_match": expected["model_ids"] == actual["model_ids"],
        "row_counts_match": all(
            expected[key] == actual[key]
            for key in (
                "prediction_row_count",
                "per_series_metric_row_count",
                "aggregate_metric_row_count",
            )
        ),
        "artifact_checksums_match": (
            expected["artifact_checksums"] == actual["artifact_checksums"]
        ),
        "locked_final_not_accessed": (
            not expected["locked_final_target_accessed"]
            and not actual["locked_final_target_accessed"]
        ),
    }
    report = {
        "status": "passed" if all(checks.values()) else "failed",
        "reference_run_id": expected["run_id"],
        "reproduction_run_id": actual["run_id"],
        "checks": checks,
        "expected_artifact_checksums": expected["artifact_checksums"],
        "actual_artifact_checksums": actual["artifact_checksums"],
    }
    report_path = Path(actual_run["output_dir"]) / "reproducibility_report.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    return {**report, "report_path": str(report_path)}
