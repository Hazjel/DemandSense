# DemandSense Architecture Decisions

| Field | Value |
|---|---|
| Status | Accepted for M0 |
| Version | 0.1.0 |
| Date | 2026-09-15 |

## ADR-001: Python environment

- Decision: Python 3.12 with a project-local `.venv` managed through `python -m venv` and `pip`.
- Reason: the system environment contains unrelated packages and conflicting transitive dependencies.
- Consequence: commands use `.venv/Scripts/python.exe`; direct project dependencies live in `pyproject.toml` and the resolved environment is frozen after a clean installation.

## ADR-002: Data processing

- Decision: Polars lazy queries and Parquet with Zstandard compression.
- Reason: the release profile contains every eligible series in one store, while lazy scanning and streaming reduce memory pressure.
- Consequence: conversions to pandas or NumPy occur only at model boundaries.

## ADR-003: Global machine-learning model

- Decision: XGBoost with `tree_method=hist` and `device=cuda`.
- Reason: CUDA training passed on the available RTX 3060 Laptop GPU; the installed LightGBM build did not provide the CUDA learner.
- Consequence: CPU fallback remains available, and resource use is measured in every reported run.

## ADR-004: Foundation-model spike

- Decision: begin with `amazon/chronos-bolt-small` and batch size 8.
- Reason: the workstation has 6 GB VRAM; the small checkpoint and conservative batch provide a safe starting point.
- Consequence: batch size is increased only after a successful memory-measured spike. TimesFM remains a stretch model.

## ADR-005: Application containers

- Decision: one application image, two Docker Compose services.
- Reason: API and dashboard retain separate lifecycles without duplicating build definitions.
- Consequence: the dashboard waits for the API health check and only reads persisted outputs.

## ADR-006: Initial benchmark population

- Decision: `CA_1`, seed `42`, 28-day horizon, and the documented zero-sales segmentation thresholds.
- Reason: a deterministic store and seed avoid choosing the benchmark after observing model results.
- Consequence: the release benchmark includes all eligible `CA_1` series; smaller cohorts are engineering-only.
