from __future__ import annotations

import gc
import json
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import numpy as np
import polars as pl
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from demandsense.config import PROJECT_ROOT
from demandsense.evaluation.features import (
    MAX_TARGET_LAG,
    build_training_frame,
    load_series_catalog,
)
from demandsense.evaluation.metrics import forecast_metrics
from demandsense.evaluation.models import (
    FoldContext,
    load_fold_context,
    predict_chronos_bolt,
    train_predict_xgboost,
)
from demandsense.evaluation.protocol import (
    EvaluationProtocol,
    FoldSpec,
    load_evaluation_protocol,
    validate_evaluation_protocol,
)
from demandsense.evaluation.runner import (
    _aggregate_metrics,
    _sha256,
    _stable_identifier,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BaselineReference(StrictModel):
    directory: Path
    run_id: str
    aggregate_metrics_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    per_series_metrics_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")


class XGBoostSpec(StrictModel):
    device: Literal["cuda", "cpu"]
    training_window_days: int = Field(ge=112)
    num_boost_round: int = Field(ge=1)
    max_depth: int = Field(ge=1)
    learning_rate: float = Field(gt=0, le=1)
    min_child_weight: float = Field(ge=0)
    subsample: float = Field(gt=0, le=1)
    colsample_bytree: float = Field(gt=0, le=1)
    reg_lambda: float = Field(ge=0)
    max_bin: int = Field(ge=2)
    random_seed: int
    feature_sets: list[Literal["xgb_lag", "xgb_calendar", "xgb_full"]]

    @model_validator(mode="after")
    def feature_sets_are_complete_and_unique(self) -> XGBoostSpec:
        expected = ["xgb_lag", "xgb_calendar", "xgb_full"]
        if self.feature_sets != expected:
            raise ValueError(f"feature_sets must be frozen as {expected}")
        return self


class ChronosSpec(StrictModel):
    model_id: str
    revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    device: Literal["cuda"]
    context_length: int = Field(ge=1)
    batch_size: int = Field(ge=1)
    point_forecast: Literal["mean"]
    quantile_levels: list[float]
    quantile_crossing_policy: Literal["sort"]
    local_files_only: Literal[True]

    @model_validator(mode="after")
    def quantiles_are_frozen(self) -> ChronosSpec:
        if self.quantile_levels != [0.1, 0.5, 0.9]:
            raise ValueError("quantile_levels must be frozen as [0.1, 0.5, 0.9]")
        return self


class StatisticsSpec(StrictModel):
    bootstrap_seed: int
    bootstrap_iterations: int = Field(ge=100)
    confidence_level: float = Field(gt=0, lt=1)


class ChallengerSuiteSpec(StrictModel):
    suite_version: str
    protocol_path: Path
    fold_scope: Literal["development_only"]
    locked_final_target_access: Literal[False]
    baseline_reference: BaselineReference
    xgboost: XGBoostSpec
    chronos: ChronosSpec
    statistics: StatisticsSpec

    def resolve_paths(self, root: Path = PROJECT_ROOT) -> ChallengerSuiteSpec:
        payload = self.model_dump()
        for target, key in (
            (payload, "protocol_path"),
            (payload["baseline_reference"], "directory"),
        ):
            path = Path(target[key])
            target[key] = path if path.is_absolute() else root / path
        return ChallengerSuiteSpec.model_validate(payload)


def load_challenger_suite(path: str | Path) -> ChallengerSuiteSpec:
    config_path = Path(path)
    if not config_path.is_absolute():
        config_path = PROJECT_ROOT / config_path
    with config_path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle)
    return ChallengerSuiteSpec.model_validate(payload).resolve_paths()


def _validate_baseline_reference(
    suite: ChallengerSuiteSpec,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    directory = suite.baseline_reference.directory
    aggregate_path = directory / "aggregate_metrics.parquet"
    per_series_path = directory / "per_series_metrics.parquet"
    manifest_path = directory / "result_manifest.json"
    checks = {
        "aggregate_checksum": (
            _sha256(aggregate_path)
            == suite.baseline_reference.aggregate_metrics_checksum
        ),
        "per_series_checksum": (
            _sha256(per_series_path)
            == suite.baseline_reference.per_series_metrics_checksum
        ),
        "run_id": (
            json.loads(manifest_path.read_text(encoding="utf-8"))["run_id"]
            == suite.baseline_reference.run_id
        ),
    }
    if not all(checks.values()):
        raise ValueError(f"Baseline reference validation failed: {checks}")
    return pl.read_parquet(aggregate_path), pl.read_parquet(per_series_path)


def _semantic_identity(
    suite: ChallengerSuiteSpec,
    protocol: EvaluationProtocol,
    series_limit: int | None,
    boost_rounds: int,
) -> dict[str, Any]:
    return {
        "suite_version": suite.suite_version,
        "fold_scope": suite.fold_scope,
        "locked_final_target_access": suite.locked_final_target_access,
        "baseline_run_id": suite.baseline_reference.run_id,
        "protocol_version": protocol.protocol_version,
        "dataset_version": protocol.dataset.dataset_version,
        "series_manifest_checksum": protocol.dataset.series_manifest_checksum,
        "xgboost": {
            **suite.xgboost.model_dump(mode="json"),
            "num_boost_round": boost_rounds,
        },
        "chronos": suite.chronos.model_dump(mode="json"),
        "statistics": suite.statistics.model_dump(mode="json"),
        "series_limit": series_limit,
    }


def _xgboost_parameters(spec: XGBoostSpec) -> dict[str, Any]:
    return {
        "objective": "reg:squarederror",
        "tree_method": "hist",
        "device": spec.device,
        "max_depth": spec.max_depth,
        "eta": spec.learning_rate,
        "min_child_weight": spec.min_child_weight,
        "subsample": spec.subsample,
        "colsample_bytree": spec.colsample_bytree,
        "lambda": spec.reg_lambda,
        "max_bin": spec.max_bin,
        "seed": spec.random_seed,
        "nthread": 8,
    }


def _append_scored_predictions(
    run_id: str,
    protocol: EvaluationProtocol,
    fold: FoldSpec,
    model_id: str,
    context: FoldContext,
    forecasts: np.ndarray,
    prediction_records: list[dict[str, Any]],
    metric_records: list[dict[str, Any]],
    quantiles: np.ndarray | None = None,
) -> None:
    bands = [("all", 1, protocol.temporal.horizon_days)] + [
        (f"days_{start:02d}_{end:02d}", start, end)
        for start, end in protocol.metrics.horizon_bands
    ]
    for series_index, row in enumerate(context.frame.iter_rows(named=True)):
        actual = context.actual[series_index]
        forecast = forecasts[series_index]
        for horizon_index, (predicted, observed) in enumerate(
            zip(forecast, actual, strict=True), start=1
        ):
            record = {
                "run_id": run_id,
                "protocol_version": protocol.protocol_version,
                "dataset_version": protocol.dataset.dataset_version,
                "fold_id": fold.fold_id,
                "model_id": model_id,
                "store_id": row["store_id"],
                "sku_id": row["sku_id"],
                "segment": row["segment"],
                "cutoff_date": fold.train_end,
                "forecast_date": fold.evaluation_start
                + timedelta(days=horizon_index - 1),
                "horizon": horizon_index,
                "prediction": float(predicted),
                "actual": float(observed),
                "q10": None,
                "q50": None,
                "q90": None,
            }
            if quantiles is not None:
                record.update(
                    {
                        "q10": float(quantiles[series_index, horizon_index - 1, 0]),
                        "q50": float(quantiles[series_index, horizon_index - 1, 1]),
                        "q90": float(quantiles[series_index, horizon_index - 1, 2]),
                    }
                )
            prediction_records.append(record)
        for band_name, band_start, band_end in bands:
            metrics = forecast_metrics(
                actual[band_start - 1 : band_end],
                forecast[band_start - 1 : band_end],
                float(context.rmsse_scales[series_index]),
                float(context.mase_scales[series_index]),
            )
            metric_records.append(
                {
                    "run_id": run_id,
                    "fold_id": fold.fold_id,
                    "model_id": model_id,
                    "store_id": row["store_id"],
                    "sku_id": row["sku_id"],
                    "segment": row["segment"],
                    "horizon_band": band_name,
                    "horizon_start": band_start,
                    "horizon_end": band_end,
                    "weight_revenue": float(context.weights[series_index]),
                    **metrics,
                }
            )


def _probabilistic_metrics(predictions: pl.DataFrame) -> pl.DataFrame:
    chronos = predictions.filter(pl.col("model_id") == "chronos_bolt_small")
    rows = []
    for fold_id in sorted(chronos["fold_id"].unique()):
        fold = chronos.filter(pl.col("fold_id") == fold_id)
        for segment in ["all", *sorted(fold["segment"].unique())]:
            group = fold if segment == "all" else fold.filter(pl.col("segment") == segment)
            actual = group["actual"].to_numpy()
            quantiles = {
                0.1: group["q10"].to_numpy(),
                0.5: group["q50"].to_numpy(),
                0.9: group["q90"].to_numpy(),
            }
            row: dict[str, Any] = {
                "fold_id": fold_id,
                "model_id": "chronos_bolt_small",
                "segment": segment,
                "observation_count": len(actual),
                "interval_80_coverage": float(
                    ((actual >= quantiles[0.1]) & (actual <= quantiles[0.9])).mean()
                ),
                "interval_80_mean_width": float(
                    (quantiles[0.9] - quantiles[0.1]).mean()
                ),
            }
            for level, values in quantiles.items():
                error = actual - values
                loss = np.maximum(level * error, (level - 1.0) * error)
                row[f"pinball_q{int(level * 100):02d}"] = float(loss.mean())
            rows.append(row)
    return pl.DataFrame(rows).sort("fold_id", "segment")


def _prediction_frame(records: list[dict[str, Any]]) -> pl.DataFrame:
    """Build a stable mixed-model schema even when quantiles appear late."""
    return pl.DataFrame(records, infer_schema_length=None).sort(
        "fold_id", "model_id", "store_id", "sku_id", "horizon"
    )


def _comparison_summary(
    baseline_aggregate: pl.DataFrame,
    challenger_aggregate: pl.DataFrame,
) -> dict[str, Any]:
    combined = pl.concat(
        [baseline_aggregate, challenger_aggregate], how="diagonal_relaxed"
    ).filter((pl.col("segment") == "all") & (pl.col("horizon_band") == "all"))
    ranking = (
        combined.group_by("model_id")
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
        .with_row_index("development_rank", offset=1)
    )
    return {
        "scope": "development_folds_only",
        "primary_metric": "mean_weighted_rmsse",
        "best_development_model_id": ranking["model_id"][0],
        "champion_status": "not_selected_inventory_gate_pending",
        "ranking": ranking.to_dicts(),
    }


def _paired_bootstrap(
    challenger_metrics: pl.DataFrame,
    baseline_metrics: pl.DataFrame,
    challenger_ids: list[str],
    spec: StatisticsSpec,
) -> dict[str, Any]:
    challengers = challenger_metrics.filter(pl.col("horizon_band") == "all")
    baselines = baseline_metrics.filter(pl.col("horizon_band") == "all")
    comparisons = []
    for challenger_id in challenger_ids:
        challenger = challengers.filter(pl.col("model_id") == challenger_id).select(
            "fold_id",
            "store_id",
            "sku_id",
            pl.col("rmsse").alias("challenger_rmsse"),
            "weight_revenue",
        )
        for baseline_id in ("croston_sba", "seasonal_naive_lag_7"):
            baseline = baselines.filter(pl.col("model_id") == baseline_id).select(
                "fold_id",
                "store_id",
                "sku_id",
                pl.col("rmsse").alias("baseline_rmsse"),
            )
            paired = challenger.join(
                baseline,
                on=["fold_id", "store_id", "sku_id"],
                how="inner",
                validate="1:1",
            ).sort("fold_id", "store_id", "sku_id")
            fold_ids = sorted(paired["fold_id"].unique())
            series_count = paired.filter(pl.col("fold_id") == fold_ids[0]).height
            rng = np.random.default_rng(spec.bootstrap_seed)
            indices = rng.integers(
                0,
                series_count,
                size=(spec.bootstrap_iterations, series_count),
                dtype=np.int32,
            )
            sampled_fold_differences = []
            observed_fold_differences = []
            for fold_id in fold_ids:
                fold = paired.filter(pl.col("fold_id") == fold_id)
                difference = (
                    fold["challenger_rmsse"] - fold["baseline_rmsse"]
                ).to_numpy()
                weights = fold["weight_revenue"].to_numpy()
                observed_fold_differences.append(
                    float(np.sum(difference * weights) / np.sum(weights))
                )
                sampled_fold_differences.append(
                    np.sum(difference[indices] * weights[indices], axis=1)
                    / np.sum(weights[indices], axis=1)
                )
            samples = np.mean(np.stack(sampled_fold_differences), axis=0)
            alpha = 1.0 - spec.confidence_level
            lower, upper = np.quantile(samples, [alpha / 2.0, 1.0 - alpha / 2.0])
            observed = float(np.mean(observed_fold_differences))
            comparisons.append(
                {
                    "challenger_model_id": challenger_id,
                    "baseline_model_id": baseline_id,
                    "estimand": "mean_fold_weighted_rmsse_difference",
                    "difference": observed,
                    "confidence_level": spec.confidence_level,
                    "ci_lower": float(lower),
                    "ci_upper": float(upper),
                    "lower_is_better": True,
                    "interval_excludes_zero": bool(lower > 0 or upper < 0),
                    "bootstrap_seed": spec.bootstrap_seed,
                    "bootstrap_iterations": spec.bootstrap_iterations,
                    "series_clusters": series_count,
                    "fold_count": len(fold_ids),
                }
            )
    return {"method": "paired_series_cluster_bootstrap", "comparisons": comparisons}


def _git_commit() -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def run_challenger_suite(
    config_path: str | Path,
    output_dir: str | Path,
    series_limit: int | None = None,
    num_boost_round: int | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    suite = load_challenger_suite(config_path)
    protocol = load_evaluation_protocol(suite.protocol_path)
    validation = validate_evaluation_protocol(protocol)
    if validation["status"] != "passed":
        raise ValueError(f"Evaluation protocol validation failed: {validation}")
    baseline_aggregate, baseline_per_series = _validate_baseline_reference(suite)
    folds = [fold for fold in protocol.temporal.folds if fold.role == "development"]
    if not folds or any(fold.locked for fold in folds):
        raise ValueError("challenger suite requires unlocked development folds")
    catalog = load_series_catalog(protocol)
    if series_limit is not None:
        catalog = catalog.head(series_limit)
    boost_rounds = num_boost_round or suite.xgboost.num_boost_round
    run_id = _stable_identifier(
        _semantic_identity(suite, protocol, series_limit, boost_rounds), "challenger"
    )
    destination = Path(output_dir)
    if not destination.is_absolute():
        destination = PROJECT_ROOT / destination
    model_dir = destination / "models"

    prediction_records: list[dict[str, Any]] = []
    metric_records: list[dict[str, Any]] = []
    operational_records = []
    context_days = max(
        suite.xgboost.training_window_days + MAX_TARGET_LAG,
        suite.chronos.context_length,
    )
    xgb_parameters = _xgboost_parameters(suite.xgboost)
    for fold in folds:
        training = build_training_frame(
            protocol, fold, catalog, suite.xgboost.training_window_days
        )
        context = load_fold_context(protocol, fold, catalog, context_days)
        for feature_set in suite.xgboost.feature_sets:
            forecasts, metadata = train_predict_xgboost(
                training,
                context,
                fold,
                feature_set,
                xgb_parameters,
                boost_rounds,
                model_dir / feature_set / f"{fold.fold_id}.json",
            )
            _append_scored_predictions(
                run_id,
                protocol,
                fold,
                feature_set,
                context,
                forecasts,
                prediction_records,
                metric_records,
            )
            operational_records.append(
                {"fold_id": fold.fold_id, "model_id": feature_set, **metadata}
            )
        del training, context
        gc.collect()

    import torch
    from chronos import ChronosBoltPipeline

    torch.manual_seed(suite.xgboost.random_seed)
    torch.cuda.manual_seed_all(suite.xgboost.random_seed)
    pipeline = ChronosBoltPipeline.from_pretrained(
        suite.chronos.model_id,
        revision=suite.chronos.revision,
        device_map=suite.chronos.device,
        local_files_only=suite.chronos.local_files_only,
    )
    for fold in folds:
        context = load_fold_context(protocol, fold, catalog, context_days)
        forecasts, quantiles, metadata = predict_chronos_bolt(
            pipeline,
            context,
            protocol.temporal.horizon_days,
            suite.chronos.context_length,
            suite.chronos.batch_size,
            suite.chronos.quantile_levels,
        )
        _append_scored_predictions(
            run_id,
            protocol,
            fold,
            "chronos_bolt_small",
            context,
            forecasts,
            prediction_records,
            metric_records,
            quantiles,
        )
        operational_records.append(
            {"fold_id": fold.fold_id, "model_id": "chronos_bolt_small", **metadata}
        )
        del context
        gc.collect()

    predictions = _prediction_frame(prediction_records)
    per_series = pl.DataFrame(metric_records).sort(
        "fold_id", "model_id", "store_id", "sku_id", "horizon_start"
    )
    aggregate = _aggregate_metrics(metric_records)
    selected_keys = catalog.select("store_id", "sku_id")
    selected_baseline_metrics = baseline_per_series.join(
        selected_keys, on=["store_id", "sku_id"], how="inner"
    )
    selected_baseline_aggregate = _aggregate_metrics(
        selected_baseline_metrics.to_dicts()
    )
    comparison = _comparison_summary(selected_baseline_aggregate, aggregate)
    probabilistic = _probabilistic_metrics(predictions)
    bootstrap = _paired_bootstrap(
        per_series,
        selected_baseline_metrics,
        [*suite.xgboost.feature_sets, "chronos_bolt_small"],
        suite.statistics,
    )

    destination.mkdir(parents=True, exist_ok=True)
    artifact_frames = {
        "challenger_predictions": predictions,
        "challenger_per_series_metrics": per_series,
        "challenger_aggregate_metrics": aggregate,
        "probabilistic_metrics": probabilistic,
    }
    artifact_paths: dict[str, Path] = {}
    for name, frame in artifact_frames.items():
        path = destination / f"{name}.parquet"
        frame.write_parquet(path, compression="zstd", statistics=True)
        artifact_paths[name] = path
    for name, payload in (
        ("comparison_summary", comparison),
        ("paired_bootstrap", bootstrap),
    ):
        path = destination / f"{name}.json"
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        artifact_paths[name] = path
    core_checksums = {name: _sha256(path) for name, path in artifact_paths.items()}
    model_checksums = {
        str(path.relative_to(destination)).replace("\\", "/"): _sha256(path)
        for path in sorted(model_dir.rglob("*.json"))
    }
    result_manifest = {
        "status": "complete",
        "run_id": run_id,
        "suite_version": suite.suite_version,
        "protocol_version": protocol.protocol_version,
        "dataset_version": protocol.dataset.dataset_version,
        "baseline_run_id": suite.baseline_reference.run_id,
        "profile": "release" if series_limit is None else "smoke",
        "series_count": catalog.height,
        "fold_ids": [fold.fold_id for fold in folds],
        "model_ids": [*suite.xgboost.feature_sets, "chronos_bolt_small"],
        "prediction_row_count": predictions.height,
        "per_series_metric_row_count": per_series.height,
        "aggregate_metric_row_count": aggregate.height,
        "maximum_target_date_accessed": str(max(fold.evaluation_end for fold in folds)),
        "locked_final_target_accessed": False,
        "best_development_model_id": comparison["best_development_model_id"],
        "champion_status": comparison["champion_status"],
        "core_artifact_checksums": core_checksums,
        "model_artifact_checksums": model_checksums,
    }
    manifest_path = destination / "result_manifest.json"
    manifest_path.write_text(
        json.dumps(result_manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    operational = {
        **result_manifest,
        "source_git_commit": _git_commit(),
        "created_at": datetime.now(UTC).isoformat(),
        "runtime_seconds": time.perf_counter() - started,
        "model_runs": operational_records,
        "result_manifest_checksum": _sha256(manifest_path),
        "torch_version": torch.__version__,
        "cuda_device": torch.cuda.get_device_name(0),
        "chronos_model_id": suite.chronos.model_id,
        "chronos_revision": suite.chronos.revision,
    }
    operational_path = destination / "run_metadata.json"
    operational_path.write_text(
        json.dumps(operational, indent=2, sort_keys=True), encoding="utf-8"
    )
    return {
        **result_manifest,
        "output_dir": str(destination),
        "ranking": comparison["ranking"],
        "runtime_seconds": operational["runtime_seconds"],
        "result_manifest_checksum": operational["result_manifest_checksum"],
    }
