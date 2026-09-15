# DemandSense M0 Execution Report

> Historical M0 closure record. M1 later regenerated all profiles under schema
> `1.2.0`; current dataset identifiers are recorded in `M1_EXECUTION_REPORT.md`.

| Field | Value |
|---|---|
| Status | Complete |
| Date | 2026-09-15 |
| Blocker | None |

## Completed

- Git repository initialized on branch `main`.
- Isolated Python 3.12.3 environment created at `.venv` using `python -m venv` and `pip`.
- Exact environment captured in `requirements.lock`.
- `pip check` reports no broken requirements.
- Project package, CLI, three execution profiles, canonical validator, M5 adapter, API, dashboard, and Docker Compose path created.
- XGBoost 3.4.1 CUDA training passed.
- PyTorch 2.5.1 with CUDA 12.1 detects the NVIDIA GeForce RTX 3060 Laptop GPU.
- `amazon/chronos-bolt-small` loaded on CUDA and produced mean and three-quantile forecasts for two synthetic series over 28 periods.
- Chronos cold-start spike completed in approximately 21 seconds.
- API live smoke test returned HTTP 200 for `/health` and `/metadata`.
- Streamlit live smoke test returned HTTP 200.
- Docker Compose configuration validation passed.
- Ten automated tests pass, including end-to-end mini M5 CSV-to-Parquet, dataset-versioning, manifest-contract, event-semantics, and API-metadata tests.
- Ruff reports no source violations.
- Kaggle competition access is accepted and all five official M5 files are downloaded.
- The real-data smoke pipeline produced 58,230 canonical daily rows for 30 `CA_1` series over 1,941 days (2011-01-29 through 2016-05-22).
- Canonical validation passed with zero duplicate keys, zero negative quantities, zero missing required values, and no missing required columns.
- The fixed cohort contains 1 fast, 14 medium, and 15 intermittent series; all 30 selected series are included.
- Source file sizes and SHA-256 checksums are recorded in `data/processed/m5/smoke/source_manifest.json`.
- Dataset version `m5-smoke-9063d67fc1f5` is recorded in every series-manifest row and in `dataset_metadata.json` under schema version `1.0.0`.
- Manifest validation passes with zero duplicate keys, null required values, invalid segments, or invalid history values.
- Rows without an M5 calendar event retain `event_name = null`; event labels are populated only for the 4,740 rows with `event_flag = true`.
- API metadata reads the validated dataset metadata instead of reporting a static unprepared state.
- Gate A hardware evidence records 235.58 GB free on drive D at the final M0 audit.

## Real-data smoke evidence

The official Kaggle archive was downloaded after the competition rules were accepted. The adapter used `sales_train_evaluation.csv`, `calendar.csv`, and `sell_prices.csv` and generated:

- `data/processed/m5/smoke/demand_daily.parquet` (58,230 rows; 68,839 bytes)
- `data/processed/m5/smoke/series_manifest.parquet` (30 rows; 4,007 bytes)
- `data/processed/m5/smoke/validation_report.json`
- `data/processed/m5/smoke/source_manifest.json`
- `data/processed/m5/smoke/dataset_metadata.json`

The smoke cohort has a 59.29% zero-sales observation ratio. `unit_price` is null for 12.32% of rows, primarily where no weekly price exists before a product is sold. Price is not a required field in the Gate A canonical validator; the missingness must be handled explicitly and without future information during M1 feature engineering.

## Non-blocking environment notes

- Starlette 1.6.0 emits an upstream AnyIO alias deprecation warning while importing its test client. All tests pass; the warning does not affect the application or M0 acceptance.
- Docker Compose configuration validates and exposes the expected `api` and `dashboard` services. The Docker Desktop daemon was not running during the final audit, so image build and container-runtime smoke testing remain scheduled for the application/release gates rather than Gate A.

## Gate decision

**Gate A passed.** Scope is fixed, official dataset access is confirmed, workstation capacity is recorded, GPU spikes pass, and the real M5 smoke artifact passes canonical validation. M0 is complete and M1 may begin. This decision does not imply that full-store processing, temporal leakage tests, or model evaluation have passed; those remain later milestones and gates.
