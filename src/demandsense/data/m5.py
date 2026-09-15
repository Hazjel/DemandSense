from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

from demandsense.config import ProjectConfig
from demandsense.data.validation import validate_canonical, validate_series_manifest

ID_COLUMNS = ["id", "item_id", "dept_id", "cat_id", "store_id", "state_id"]
SCHEMA_VERSION = "1.0.0"
ADAPTER_VERSION = "m5-v1"
COHORT_DEFINITION_VERSION = "zero-sales-ratio-v1"


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
        }
        payload = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
        digest = hashlib.sha256(payload).hexdigest()[:12]
        return f"m5-{self.config.data.profile}-{digest}"

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

        sales = pl.scan_csv(files.sales)
        store_sales = sales.filter(pl.col("store_id") == self.config.data.store_id)
        if self.config.data.series_limit is not None:
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
        canonical = (
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

        validation = validate_canonical(canonical).to_dict()
        if validation["status"] != "passed":
            raise ValueError(f"Canonical validation failed: {validation}")

        output_dir = self.config.paths.processed_dir / self.config.data.profile
        output_dir.mkdir(parents=True, exist_ok=True)
        demand_path = output_dir / "demand_daily.parquet"
        canonical.write_parquet(demand_path, compression="zstd", statistics=True)

        segment = (
            pl.when(pl.col("zero_sales_ratio") < self.config.segmentation.fast_max_zero_ratio)
            .then(pl.lit("fast"))
            .when(
                pl.col("zero_sales_ratio")
                > self.config.segmentation.intermittent_min_zero_ratio
            )
            .then(pl.lit("intermittent"))
            .otherwise(pl.lit("medium"))
        )
        manifest = (
            canonical.group_by("store_id", "sku_id")
            .agg(
                (pl.col("quantity_sold") == 0).mean().alias("zero_sales_ratio"),
                pl.len().alias("history_days"),
            )
            .with_columns(
                pl.lit(dataset_version).alias("dataset_version"),
                segment.alias("segment"),
                pl.lit(self.config.data.selection_seed).alias("selection_seed"),
                pl.lit(self.config.data.profile).alias("cohort_role"),
                pl.lit(True).alias("included"),
                pl.lit(None, dtype=pl.String).alias("exclusion_reason"),
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
            )
            .sort("store_id", "sku_id")
        )
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
            "validation_status": validation["status"],
            "manifest_validation_status": manifest_validation["status"],
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
            "validation": validation,
            "manifest_validation": manifest_validation,
        }
