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
from demandsense.data.validation import validate_canonical

ID_COLUMNS = ["id", "item_id", "dept_id", "cat_id", "store_id", "state_id"]


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

    def prepare(self) -> dict[str, Any]:
        files = self.discover_files()
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
                pl.concat_str(
                    ["event_name_1", "event_name_2"], separator=" | ", ignore_nulls=True
                ).alias("event_name"),
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
                segment.alias("segment"),
                pl.lit(self.config.data.selection_seed).alias("selection_seed"),
                pl.lit(self.config.data.profile).alias("cohort_role"),
                pl.lit(True).alias("included"),
                pl.lit(None, dtype=pl.String).alias("exclusion_reason"),
            )
            .sort("store_id", "sku_id")
        )
        manifest_path = output_dir / "series_manifest.parquet"
        manifest.write_parquet(manifest_path, compression="zstd", statistics=True)

        validation = validate_canonical(canonical).to_dict()
        validation_path = output_dir / "validation_report.json"
        validation_path.write_text(json.dumps(validation, indent=2), encoding="utf-8")

        source_manifest = self.source_manifest(files)
        source_manifest_path = output_dir / "source_manifest.json"
        source_manifest_path.write_text(
            json.dumps(source_manifest, indent=2), encoding="utf-8"
        )
        return {
            "demand_path": str(demand_path),
            "manifest_path": str(manifest_path),
            "validation_path": str(validation_path),
            "source_manifest_path": str(source_manifest_path),
            "validation": validation,
        }
