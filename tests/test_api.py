import json
from pathlib import Path

from fastapi.testclient import TestClient

from demandsense.api import app


def test_health_endpoint() -> None:
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_metadata_endpoint_reads_validated_dataset(
    tmp_path: Path, monkeypatch,
) -> None:
    metadata_path = tmp_path / "dataset_metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "dataset_version": "m5-smoke-test123",
                "profile": "smoke",
                "validation_status": "passed",
                "series_count": 30,
                "row_count": 58_230,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEMANDSENSE_METADATA_PATH", str(metadata_path))

    response = TestClient(app).get("/metadata")

    assert response.status_code == 200
    assert response.json() == {
        "project": "DemandSense",
        "stage": "M0-complete",
        "active_model": "not_selected",
        "dataset_version": "m5-smoke-test123",
        "dataset_profile": "smoke",
        "validation_status": "passed",
        "series_count": 30,
        "row_count": 58_230,
    }
