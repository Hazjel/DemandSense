from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI

from demandsense import __version__

app = FastAPI(title="DemandSense API", version=__version__)


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "version": __version__,
        "timestamp": datetime.now(UTC).isoformat(),
    }


@app.get("/metadata")
def metadata() -> dict[str, str]:
    return {
        "project": "DemandSense",
        "stage": "M0",
        "active_model": "not_selected",
        "dataset_version": "not_prepared",
    }
