# DemandSense Architecture

| Field | Value |
|---|---|
| Status | Accepted for implementation |
| Version | 0.3.0 |
| Date | 2026-09-15 |

## 1. Architectural goals

- Reproducible from raw source to report.
- Leakage-safe and configuration-driven.
- Runnable locally using the available storage and GPU, with CPU fallbacks for unsupported operations.
- Batch-first; expensive inference is not performed on dashboard requests.
- Source-independent after canonicalization.
- Observable enough to diagnose stale data, failed pipelines, drift, and model degradation.
- Easy to extend with an Indonesian UMKM adapter.

## 2. System context

```text
M5 files                 Future UMKM export
    |                           |
    v                           v
M5 adapter                 UMKM adapter
    |                           |
    +------> Canonical demand tables <------+
                         |
                         v
               Validation and features
                         |
             +-----------+-----------+
             |                       |
             v                       v
       Training/backtest        Batch inference
             |                       |
             v                       v
       Model artifacts        Forecast outputs
                                     |
                                     v
                            Inventory simulation
                                     |
                         +-----------+-----------+
                         |                       |
                         v                       v
                    Read-only API           Dashboard
```

## 3. Logical layers

### 3.1 Data layer

Responsibilities:

- source download instructions and checksums;
- immutable raw storage;
- source adapter execution;
- canonical Parquet tables;
- validation reports and series manifest;
- dataset version metadata.

Recommended local storage:

```text
data/
├── raw/          # ignored by Git
├── interim/      # ignored by Git
├── processed/    # ignored by Git except tiny fixtures
└── fixtures/     # small synthetic test data committed to Git
```

DuckDB may query Parquet outputs without requiring a separate database server.

### 3.2 Experiment layer

Responsibilities:

- temporal fold generation;
- feature computation at a declared cutoff;
- model training and inference through a common interface;
- metric and statistical analysis;
- experiment metadata and artifact persistence;
- champion recommendation without automatic promotion.

Conceptual model interface:

```text
fit(train_data, config) -> model_artifact
predict(history, future_known_data, horizon, config) -> forecast_table
```

Zero-shot foundation models may implement `fit` as model loading and validation, but must still record checkpoint and configuration versions.

### 3.3 Decision layer

Responsibilities:

- transform forecast distributions or point estimates into demand during lead time;
- calculate safety stock under a named policy;
- simulate replenishment and inventory flow;
- calculate service and cost metrics;
- persist recommendation outputs with assumption versions.

The decision layer must not be embedded inside the dashboard.

### 3.4 Serving layer

The API serves persisted outputs only.

Proposed endpoints:

| Endpoint | Purpose |
|---|---|
| `GET /health` | Service health and artifact availability |
| `GET /metadata` | Active model, dataset, and forecast versions |
| `GET /forecasts` | Filtered forecasts by store/SKU/date |
| `GET /recommendations` | Filtered inventory recommendations |
| `GET /metrics` | Approved evaluation summaries |
| `GET /model-card` | Model limitations and intended use |

No write or purchasing endpoint is included in the MVP.

### 3.5 Presentation layer

Minimum dashboard pages:

- Overview: data freshness, active model, aggregate forecast, and alerts.
- SKU Explorer: history, point/interval forecast, segment, and recommendation.
- Model Comparison: development and final metrics by segment.
- Inventory Simulation: policy comparison and cost sensitivity.
- Monitoring: data-quality, drift, performance, and pipeline status.
- Limitations: known assumptions and appropriate use.

## 4. Batch workflow

```text
1. Validate configuration
2. Validate source files and checksums
3. Run source adapter
4. Validate canonical data
5. Build cutoff-safe features
6. Train/load configured models
7. Generate forecasts
8. Validate forecast schema and non-negativity policy
9. Run inventory simulation
10. Persist outputs and metadata atomically
11. Generate monitoring summary
12. Expose the newest successful artifact version
```

A failed batch must not replace the most recent successful forecast.

### Execution profiles

The same pipeline supports three configuration-driven profiles:

| Profile | Population | Purpose | Artifact policy |
|---|---|---|---|
| `smoke` | 30-60 fixed series | Schema, leakage, API, and integration checks | Small artifacts may be retained for CI fixtures |
| `development` | Approximately 300 stratified series | Fast feature and hyperparameter iteration | Retain metrics and selected artifacts |
| `release` | All eligible series in one selected store | Reported backtests and locked final evaluation | Retain complete reproducibility artifacts |

GPU acceleration is used for compatible gradient boosting and foundation-model inference. Data transformation remains column-pruned and Parquet-backed because sufficient storage does not remove memory, I/O, or reproducibility constraints. Workloads should be batched by model or series when required by VRAM.

## 5. Proposed project structure

```text
demandsense/
├── configs/
│   ├── base.yaml
│   ├── portfolio.yaml
│   └── research_umkm.yaml
├── data/
│   ├── raw/
│   ├── interim/
│   ├── processed/
│   └── fixtures/
├── docs/
├── notebooks/
│   ├── 01_eda.ipynb
│   └── 02_experiment_review.ipynb
├── src/demandsense/
│   ├── data/
│   │   ├── adapters/
│   │   │   ├── base.py
│   │   │   ├── m5.py
│   │   │   └── umkm.py
│   │   ├── contracts.py
│   │   └── validation.py
│   ├── features/
│   ├── models/
│   │   ├── base.py
│   │   ├── baselines.py
│   │   ├── global_ml.py
│   │   └── foundation.py
│   ├── evaluation/
│   ├── inventory/
│   ├── monitoring/
│   └── pipelines/
├── api/
├── dashboard/
├── tests/
│   ├── unit/
│   ├── integration/
│   └── smoke/
├── artifacts/       # ignored by Git except example summaries
├── reports/
├── Dockerfile
├── compose.yaml
└── README.md
```

## 6. Configuration design

Configuration controls:

- data source and version;
- selected store, execution profile, and cohort manifests;
- temporal folds and horizon;
- feature availability assumptions;
- models and checkpoints;
- hyperparameters and seeds;
- inventory assumptions;
- artifact locations;
- monitoring thresholds.

Secrets, credentials, and private paths must not be stored in committed configuration.

## 7. Reliability behavior

- Writes use a temporary run directory and become active only after validation succeeds.
- Every batch has a unique run ID.
- Failed steps emit structured error information.
- Retrying a run must not duplicate canonical records.
- The API exposes the timestamp of the newest successful forecast.
- The dashboard visibly warns when artifacts are missing or stale.
- A simple baseline forecast remains available if an advanced model fails.

## 8. Monitoring design

### 8.1 Data quality

- row count and date coverage;
- duplicate primary keys;
- missing and invalid values;
- missing-price and join rates;
- selected-series coverage;
- schema changes.

### 8.2 Drift

- zero-sales ratio shift;
- quantity and price distribution shift;
- changes in category/store coverage;
- forecast distribution shift.

Drift is an alert signal, not proof that performance degraded.

### 8.3 Performance

- rolling WAPE/MASE or selected metrics when actuals arrive;
- forecast bias;
- interval coverage;
- error by demand segment and horizon.

### 8.4 Operational

- pipeline status and duration;
- artifact freshness;
- API error rate and response time;
- model load/inference failures;
- disk and artifact growth.

## 9. Security and privacy

- Public M5 data and future private UMKM data use separate storage paths.
- Private raw data is never committed.
- API is read-only in the MVP.
- No customer PII is needed for forecasting.
- Logs must not contain raw transaction payloads or secrets.
- A future hosted deployment requires authentication and an explicit access review before private data is uploaded.

## 10. Deployment strategy

### MVP

- Run locally through documented Python commands or containers.
- Train and forecast in batch.
- Serve persisted data through API and dashboard containers.

### Optional hosted demo

- Upload only non-sensitive sample data and cached outputs.
- Do not perform heavy model training on web requests.
- Keep the hosted demo read-only.

### Future research deployment

- Add the UMKM adapter and private storage configuration.
- Re-run validation, experiments, and model selection.
- Do not automatically promote the M5 champion to UMKM data.

## 11. Confirmed architecture decisions

- [x] Polars lazy queries and Parquet for transformation; pandas/NumPy only at model boundaries.
- [x] XGBoost is the mandatory global ML model; CUDA training passed during M0.
- [x] Lightweight JSON/Parquet experiment registry for MVP; MLflow remains post-MVP.
- [x] `amazon/chronos-bolt-small` with initial batch size 8 on the 6 GB GPU.
- [x] TimesFM remains a stretch model and cannot delay the portfolio release.
- [x] One Docker image with separate API and dashboard Compose services.
