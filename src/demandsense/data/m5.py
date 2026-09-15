from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl

from demandsense.config import ProjectConfig
from demandsense.data.quality import build_quality_report, validate_raw_m5
from demandsense.data.validation import validate_canonical, validate_series_manifest

ID_COLUMNS = ["id", "item_id", "dept_id", "cat_id", "store_id", "state_id"]
SCHEMA_VERSION = "1.1.0"
ADAPTER_VERSION = "m5-v2"
COHORT_DEFINITION_VERSION = "pretest-zero-sales-ratio-v2"
SEGMENT_ORDER = ("fast", "medium", "intermittent")


@dataclass(frozen=True)
class M5Files:
    sales: Path
    calendar: Path
    prices: Path


def _sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


class M5Adapter:
    def __init__(self, config: ProjectConfig) -> None:
        self.config = config

    def discover_files(self) -> M5Files:
        root = self.config.paths.raw_dir
        evaluation = root / "sales_train_evaluation.csv"
        validation = root / "sales_train_validation.csv"
        sales = evaluation if evaluation.exists() else validation
        files = M5Files(
            sales=sales,
            calendar=root / "calendar.csv",
            prices=root / "sell_prices.csv",
        )
        missing = [str(path) for path in files.__dict__.values() if not path.exists()]
        if missing:
            raise FileNotFoundError("Missing required M5 files: " + ", ".join(missing))
        return files

    @staticmethod
    def _headers(path: Path) -> list[str]:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return next(csv.reader(handle))

    def source_manifest(self, files: M5Files) -> dict[str, Any]:
        return {
            "source": "m5",
            "created_at": datetime.now(UTC).isoformat(),
            "files": {
                path.name: {"bytes": path.stat().st_size, "sha256": _sha256(path)}
                for path in files.__dict__.values()
            },
        }

    def dataset_version(self, source_manifest: dict[str, Any]) -> str:
        identity = {
            "schema_version": SCHEMA_VERSION,
            "adapter_version": ADAPTER_VERSION,
            "source": "m5",
            "files": {
                name: record["sha256"]
                for name, record in sorted(source_manifest["files"].items())
            },
            "store_id": self.config.data.store_id,
            "profile": self.config.data.profile,
            "series_limit": self.config.data.series_limit,
            "selection_seed": self.config.data.selection_seed,
            "cohort_definition_version": COHORT_DEFINITION_VERSION,
            "segmentation": self.config.segmentation.model_dump(mode="json"),
            "forecast": self.config.forecast.model_dump(mode="json"),
            "validation": self.config.validation.model_dump(mode="json"),
        }
        payload = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
        digest = hashlib.sha256(payload).hexdigest()[:12]
        return f"m5-{self.config.data.profile}-{digest}"

    def _selection_score(self, sku_id: str) -> str:
        value = (
            f"{self.config.data.selection_seed}:"
            f"{self.config.data.store_id}:{sku_id}"
        )
        return hashlib.sha256(value.encode()).hexdigest()

    def _build_manifest(
        self,
        canonical: pl.DataFrame,
        dataset_version: str,
        reference_end_date: date,
    ) -> pl.DataFrame:
        keys = ["store_id", "sku_id"]
        reference = canonical.filter(pl.col("date") <= reference_end_date)
        full_history = canonical.group_by(keys).agg(
            pl.len().alias("history_days"),
        )
        manifest = (
            reference.group_by(keys)
            .agg(
                pl.len().alias("reference_history_days"),
                pl.col("quantity_sold").sum().alias("total_sales"),
                pl.col("date")
                .filter(
                    pl.col("unit_price").is_not_null()
                    | (pl.col("quantity_sold") > 0)
                )
                .min()
                .alias("active_start_date"),
                pl.col("date")
                .filter(pl.col("quantity_sold") > 0)
                .max()
                .alias("last_positive_date"),
                (pl.col("quantity_sold") == 0).mean().alias("zero_sales_ratio"),
                pl.col("unit_price").is_null().mean().alias("missing_price_ratio"),
            )
            .join(full_history, on=keys, how="left")
            .with_columns(
                (
                    pl.lit(reference_end_date) - pl.col("active_start_date")
                )
                .dt.total_days()
                .add(1)
                .alias("active_history_days"),
                (
                    pl.lit(reference_end_date) - pl.col("last_positive_date")
                )
                .dt.total_days()
                .alias("trailing_zero_days"),
            )
            .with_columns(
                pl.when(
                    pl.col("zero_sales_ratio")
                    < self.config.segmentation.fast_max_zero_ratio
                )
                .then(pl.lit("fast"))
                .when(
                    pl.col("zero_sales_ratio")
                    > self.config.segmentation.intermittent_min_zero_ratio
                )
                .then(pl.lit("intermittent"))
                .otherwise(pl.lit("medium"))
                .alias("segment"),
                (
                    (pl.col("total_sales") > 0)
                    & (
                        pl.col("active_history_days")
                        >= self.config.forecast.minimum_history_days
                    )
                ).alias("eligible"),
            )
            .with_columns(
                pl.when(pl.col("total_sales") <= 0)
                .then(pl.lit("no_positive_sales_in_reference"))
                .when(pl.col("active_start_date").is_null())
                .then(pl.lit("no_observed_activity_in_reference"))
                .when(
                    pl.col("active_history_days")
                    < self.config.forecast.minimum_history_days
                )
                .then(pl.lit("insufficient_active_history"))
                .otherwise(pl.lit(None, dtype=pl.String))
                .alias("eligibility_exclusion_reason")
            )
        )
        active_price_profile = (
            reference.join(
                manifest.select(keys + ["active_start_date"]),
                on=keys,
                how="left",
            )
            .filter(pl.col("date") >= pl.col("active_start_date"))
            .group_by(keys)
            .agg(
                pl.col("unit_price")
                .is_null()
                .mean()
                .alias("active_missing_price_ratio")
            )
        )
        manifest = manifest.join(active_price_profile, on=keys, how="left")

        if self.config.data.profile == "development":
            assert self.config.data.series_limit is not None
            quota, remainder = divmod(
                self.config.data.series_limit, len(SEGMENT_ORDER)
            )
            selected_parts: list[pl.DataFrame] = []
            scored = manifest.with_columns(
                pl.col("sku_id")
                .map_elements(self._selection_score, return_dtype=pl.String)
                .alias("_selection_score")
            )
            for index, segment_name in enumerate(SEGMENT_ORDER):
                segment_quota = quota + (1 if index < remainder else 0)
                selected_parts.append(
                    scored.filter(
                        pl.col("eligible") & (pl.col("segment") == segment_name)
                    )
                    .sort("_selection_score", "sku_id")
                    .head(segment_quota)
                    .select(keys)
                )
            selected = pl.concat(selected_parts).with_columns(
                pl.lit(True).alias("_selected")
            )
            manifest = (
                manifest.join(selected, on=keys, how="left")
                .with_columns(
                    pl.col("_selected").fill_null(False).alias("included")
                )
                .with_columns(
                    pl.when(pl.col("included"))
                    .then(pl.lit(None, dtype=pl.String))
                    .when(~pl.col("eligible"))
                    .then(pl.col("eligibility_exclusion_reason"))
                    .otherwise(pl.lit("not_selected_for_development"))
                    .alias("exclusion_reason")
                )
                .drop("_selected")
            )
        else:
            manifest = manifest.with_columns(
                pl.col("eligible").alias("included"),
                pl.col("eligibility_exclusion_reason").alias("exclusion_reason"),
            )

        return (
            manifest.with_columns(
                pl.lit(dataset_version).alias("dataset_version"),
                pl.lit(reference_end_date).alias("reference_end_date"),
                pl.lit(self.config.data.selection_seed).alias("selection_seed"),
                pl.lit(self.config.data.profile).alias("cohort_role"),
            )
            .select(
                "dataset_version",
                "store_id",
                "sku_id",
                "zero_sales_ratio",
                "history_days",
                "segment",
                "selection_seed",
                "cohort_role",
                "included",
                "exclusion_reason",
                "eligible",
                "reference_end_date",
                "reference_history_days",
                "active_start_date",
                "active_history_days",
                "last_positive_date",
                "trailing_zero_days",
                "total_sales",
                "missing_price_ratio",
                "active_missing_price_ratio",
            )
            .sort("store_id", "sku_id")
        )

    def prepare(self) -> dict[str, Any]:
        files = self.discover_files()
        source_manifest = self.source_manifest(files)
        dataset_version = self.dataset_version(source_manifest)
        source_manifest["dataset_version"] = dataset_version
        source_manifest["schema_version"] = SCHEMA_VERSION
        source_manifest["adapter_version"] = ADAPTER_VERSION
        headers = self._headers(files.sales)
        day_columns = sorted(
            (column for column in headers if column.startswith("d_")),
            key=lambda name: int(name.split("_")[1]),
        )
        if not day_columns:
            raise ValueError(f"No M5 day columns found in {files.sales}")
        raw_validation = validate_raw_m5(
            files.sales,
            files.calendar,
            files.prices,
            self.config.data.store_id,
            day_columns,
        )
        if raw_validation["status"] != "passed":
            raise ValueError(f"Raw M5 validation failed: {raw_validation}")

        sales = pl.scan_csv(files.sales)
        store_sales = sales.filter(pl.col("store_id") == self.config.data.store_id)
        if (
            self.config.data.profile == "smoke"
            and self.config.data.series_limit is not None
        ):
            selected = (
                store_sales.select("item_id")
                .sort("item_id")
                .head(self.config.data.series_limit)
                .collect()["item_id"]
                .to_list()
            )
            store_sales = store_sales.filter(pl.col("item_id").is_in(selected))

        sales_long = store_sales.select(ID_COLUMNS + day_columns).unpivot(
            on=day_columns,
            index=ID_COLUMNS,
            variable_name="d",
            value_name="quantity_sold",
        )

        state = self.config.data.store_id.split("_")[0]
        snap_column = f"snap_{state}"
        calendar = pl.scan_csv(files.calendar).select(
            "d",
            pl.col("date").str.to_date(),
            "wm_yr_wk",
            "event_name_1",
            "event_name_2",
            pl.col(snap_column).cast(pl.Boolean).alias("snap_eligible"),
        )
        prices = pl.scan_csv(files.prices).select(
            "store_id", "item_id", "wm_yr_wk", "sell_price"
        )

        event_present = pl.col("event_name_1").is_not_null() | pl.col(
            "event_name_2"
        ).is_not_null()
        event_name = pl.when(event_present).then(
            pl.concat_str(
                ["event_name_1", "event_name_2"], separator=" | ", ignore_nulls=True
            )
        ).otherwise(pl.lit(None, dtype=pl.String))
        canonical_all = (
            sales_long.join(calendar, on="d", how="left")
            .join(prices, on=["store_id", "item_id", "wm_yr_wk"], how="left")
            .select(
                "date",
                "store_id",
                pl.col("item_id").alias("sku_id"),
                pl.col("cat_id").alias("category"),
                pl.col("dept_id").alias("subcategory"),
                pl.col("quantity_sold").cast(pl.Float64),
                pl.col("sell_price").cast(pl.Float64).alias("unit_price"),
                pl.lit(None, dtype=pl.Boolean).alias("promotion_flag"),
                event_present.alias("event_flag"),
                event_name.alias("event_name"),
                "snap_eligible",
                pl.lit(None, dtype=pl.Float64).alias("stock_on_hand"),
                pl.lit(None, dtype=pl.Boolean).alias("stockout_flag"),
                pl.lit(None, dtype=pl.Float64).alias("unit_cost"),
                pl.lit("m5").alias("source"),
                pl.lit(datetime.now(UTC)).alias("ingested_at"),
            )
            .sort("store_id", "sku_id", "date")
            .collect(engine="streaming")
        )

        population_validation = validate_canonical(canonical_all).to_dict()
        if population_validation["status"] != "passed":
            raise ValueError(
                f"Canonical population validation failed: {population_validation}"
            )

        max_date = canonical_all["date"].max()
        if max_date is None:
            raise ValueError("Canonical M5 data has no maximum date")
        reference_end_date = max_date - timedelta(days=self.config.forecast.horizon)
        manifest = self._build_manifest(
            canonical_all, dataset_version, reference_end_date
        )
        included_keys = manifest.filter(pl.col("included")).select(
            "store_id", "sku_id"
        )
        if included_keys.is_empty():
            raise ValueError(
                "No eligible series remain after history and cohort selection rules"
            )
        canonical = (
            canonical_all.join(included_keys, on=["store_id", "sku_id"], how="inner")
            .sort("store_id", "sku_id", "date")
        )
        validation = validate_canonical(canonical).to_dict()
        if validation["status"] != "passed":
            raise ValueError(f"Selected canonical validation failed: {validation}")

        output_dir = self.config.paths.processed_dir / self.config.data.profile
        output_dir.mkdir(parents=True, exist_ok=True)
        demand_path = output_dir / "demand_daily.parquet"
        canonical.write_parquet(demand_path, compression="zstd", statistics=True)

        manifest_validation = validate_series_manifest(manifest).to_dict()
        if manifest_validation["status"] != "passed":
            raise ValueError(f"Series manifest validation failed: {manifest_validation}")
        manifest_path = output_dir / "series_manifest.parquet"
        manifest.write_parquet(manifest_path, compression="zstd", statistics=True)

        validation_path = output_dir / "validation_report.json"
        validation_path.write_text(json.dumps(validation, indent=2), encoding="utf-8")

        source_manifest_path = output_dir / "source_manifest.json"
        source_manifest_path.write_text(
            json.dumps(source_manifest, indent=2), encoding="utf-8"
        )
        generated_at = datetime.fromisoformat(source_manifest["created_at"])
        quality_report = build_quality_report(
            canonical,
            manifest,
            self.config,
            raw_validation,
            dataset_version,
            reference_end_date,
            generated_at,
        )
        if quality_report["status"] != "passed":
            raise ValueError(f"Dataset quality validation failed: {quality_report}")
        quality_report_path = output_dir / "quality_report.json"
        quality_report_path.write_text(
            json.dumps(quality_report, indent=2), encoding="utf-8"
        )
        manifest_checksum = _sha256(manifest_path)
        dataset_metadata = {
            "dataset_version": dataset_version,
            "schema_version": SCHEMA_VERSION,
            "source_name": "m5",
            "source_file_checksums": {
                name: record["sha256"]
                for name, record in source_manifest["files"].items()
            },
            "adapter_version": ADAPTER_VERSION,
            "creation_timestamp": source_manifest["created_at"],
            "selected_store": self.config.data.store_id,
            "selection_seed": self.config.data.selection_seed,
            "profile": self.config.data.profile,
            "cohort_definition_version": COHORT_DEFINITION_VERSION,
            "reference_end_date": str(reference_end_date),
            "smoke_cohort_manifest_checksum": (
                manifest_checksum if self.config.data.profile == "smoke" else None
            ),
            "development_cohort_manifest_checksum": (
                manifest_checksum if self.config.data.profile == "development" else None
            ),
            "selected_series_manifest_checksum": manifest_checksum,
            "date_range": {
                "min": validation["min_date"],
                "max": validation["max_date"],
            },
            "row_count": validation["row_count"],
            "series_count": validation["series_count"],
            "population_series_count": manifest.height,
            "eligible_series_count": manifest.filter(pl.col("eligible")).height,
            "excluded_series_count": manifest.filter(~pl.col("eligible")).height,
            "validation_status": validation["status"],
            "manifest_validation_status": manifest_validation["status"],
            "quality_status": quality_report["status"],
            "quality_warning_count": quality_report["warning_count"],
            "quality_report_checksum": _sha256(quality_report_path),
        }
        dataset_metadata_path = output_dir / "dataset_metadata.json"
        dataset_metadata_path.write_text(
            json.dumps(dataset_metadata, indent=2), encoding="utf-8"
        )
        return {
            "dataset_version": dataset_version,
            "demand_path": str(demand_path),
            "manifest_path": str(manifest_path),
            "validation_path": str(validation_path),
            "source_manifest_path": str(source_manifest_path),
            "dataset_metadata_path": str(dataset_metadata_path),
            "quality_report_path": str(quality_report_path),
            "validation": validation,
            "manifest_validation": manifest_validation,
            "quality": {
                "status": quality_report["status"],
                "warning_count": quality_report["warning_count"],
            },
        }
