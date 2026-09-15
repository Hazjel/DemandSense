# DemandSense Architecture Decisions

| Field | Value |
|---|---|
| Status | Accepted through M3 |
| Version | 0.4.0 |
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

## ADR-007: Eligibility cutoff and cohort reference window

- Decision: require positive observed sales and 112 active days by the earliest development cutoff, `2016-01-31`; determine reporting-only segments through `2016-04-24`, before the locked final window.
- Reason: every included series must be evaluable in every planned fold; counting pre-launch calendar zeros as history would admit invalid series.
- Consequence: five of 3,049 `CA_1` series are excluded, leaving 3,044 release series; sparsity and inactivity alone remain warnings.

## ADR-008: Development cohort selection

- Decision: select 100 eligible series per fast, medium, and intermittent segment using deterministic SHA-256 ranking with seed `42`.
- Reason: balanced development feedback must retain difficult intermittent demand without making sampled results the release benchmark.
- Consequence: the 300-series cohort is frozen by its versioned manifest checksum; reported final comparisons still use all 3,044 eligible release series.

## ADR-009: Frozen temporal evaluation protocol

- Decision: freeze protocol `m2-v1` with three consecutive 28-day development folds and one locked 28-day final fold; segments are reporting-only, target features have minimum lag one, transformations fit on fold training data only, and Seasonal Naive forecasts recurse beyond the available cutoff.
- Reason: fixed dates and feature-availability rules prevent random-split bias, target leakage, and accidental use of actual evaluation values at later horizons.
- Consequence: `configs/evaluation.yaml` is the versioned source of truth. The locked final targets remain inaccessible until the champion configuration is frozen. M3 subsequently satisfied Gate B with reproducible Seasonal Naive results.

## ADR-010: Baseline implementation and metric aggregation

- Decision: use recursive last-observation and Seasonal Naive forecasts, plus Croston-SBA with fixed alpha `0.10`; initialize Croston from the frozen active-start date so pre-launch zeros do not distort the event interval.
- Decision: compute RMSSE scale from the first positive training observation, use the final 28 training days of observed revenue as the WRMSSE weight, average per-series MASE, and pool errors for WAPE and normalized bias. Positive bias means overforecasting.
- Reason: these definitions match protocol `m2-v1`, remain meaningful for intermittent demand, and expose zero denominators instead of silently replacing them.
- Consequence: run `baseline-f0244fc6ddec` is the M4 comparison reference. Croston-SBA is the strongest development baseline; no final champion is selected until challenger and decision-layer evidence are available.
