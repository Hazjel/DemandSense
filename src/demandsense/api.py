from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from demandsense import __version__

app = FastAPI(title="DemandSense API", version=__version__)
DEFAULT_DATASET_METADATA_PATH = Path(
    "data/processed/m5/release/dataset_metadata.json"
)


def _load_dataset_metadata() -> dict[str, Any] | None:
    path = Path(
        os.getenv("DEMANDSENSE_METADATA_PATH", str(DEFAULT_DATASET_METADATA_PATH))
    )
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "version": __version__,
        "timestamp": datetime.now(UTC).isoformat(),
    }


@app.get("/metadata")
def metadata() -> dict[str, str | int]:
    dataset = _load_dataset_metadata()
    response: dict[str, str | int] = {
        "project": "DemandSense",
        "stage": "M1-complete",
        "active_model": "not_selected",
        "dataset_version": "not_prepared",
        "dataset_profile": "not_available",
        "validation_status": "not_available",
    }
    if dataset is not None:
        response.update(
            dataset_version=str(dataset.get("dataset_version", "unknown")),
            dataset_profile=str(dataset.get("profile", "unknown")),
            validation_status=str(dataset.get("validation_status", "unknown")),
            series_count=int(dataset.get("series_count", 0)),
            row_count=int(dataset.get("row_count", 0)),
        )
    return response
