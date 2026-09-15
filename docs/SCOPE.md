# DemandSense Scope

| Field | Value |
|---|---|
| Status | Accepted baseline scope |
| Version | 0.4.0 |
| Date | 2026-09-15 |

## 1. MVP boundary

DemandSense MVP is a local, batch-oriented system that forecasts demand and demonstrates inventory decision support. The MVP prioritizes experimental correctness, reproducibility, and a complete vertical slice over production scale.

## 2. Data scope

### 2.1 Initial source

- Source: M5 Forecasting Accuracy dataset.
- Grain after transformation: one row per `date`, `store_id`, and `sku_id`.
- Initial store count: one.
- Release population: every eligible product-store series in the selected store.
- Development cohort: approximately 300 stratified series for fast iteration.
- Smoke cohort: 30-60 fixed series for pipeline and integration tests.
- History: all available history before each temporal cutoff, subject to model context limits.
- Forecast horizon: 28 days.

### 2.2 Population and cohort strategy

The release benchmark is not a sample: it contains all series in the selected store that pass pre-defined history and data-quality rules. This reduces selection bias while keeping the first release within a coherent retail context.

The smaller development cohort must not contain only easy, high-volume products. Series are stratified into three operational segments using the proportion of zero-sales days over an agreed reference period:

- Fast-moving: less than 20% zero-sales days.
- Medium-moving: 20% to 60% zero-sales days.
- Intermittent: more than 60% zero-sales days.

Target up to 100 development series per segment. If a selected store lacks enough series in a segment, retain all eligible series in that segment and document the shortfall rather than silently changing thresholds.

Additional sampling rules:

- Exclude series with insufficient history for all required evaluation windows.
- Keep products with zero-heavy demand; do not filter them solely to improve metrics.
- Freeze the development IDs and sampling seed before model tuning.
- Freeze the full release-population manifest before reported model comparison.
- Store both cohort definitions as versioned artifacts.
- Use the smoke and development cohorts to debug and prune configurations, but report the mandatory release benchmark on the full eligible store population.

The thresholds are pragmatic MVP definitions, not universal retail classifications. A future research study may replace them with a formal ADI/CV-squared taxonomy.

M1 freezes the cohort reference window at `2016-04-24`, excluding the final 28
days from eligibility and segment assignment. A series is eligible when it has
positive observed sales and at least 112 active days by that date. Active history
begins at the first positive sale or first available price, whichever occurs first.
Development selection uses seed `42` and a deterministic hash ranking within each
segment, selecting 100 eligible series from each segment. Sparse and inactive-tail
series remain included and are reported as warnings rather than silently removed.

## 3. Functional scope

### 3.1 Data preparation

- Download instructions for source data.
- Raw data validation.
- Transformation from M5 wide sales format to canonical long format.
- Calendar and price joins.
- Demand segmentation and selection manifest.
- Processed data persisted in Parquet.

### 3.2 Forecasting

- Seasonal Naive with weekly and 28-day seasonal lags.
- At least one intermittent-demand baseline such as Croston/SBA.
- A global gradient-boosted tree model.
- At least one pretrained time-series foundation model.
- Optional ensemble if mandatory models are already complete.

### 3.3 Evaluation

- Three rolling development folds.
- One locked final 28-day test window.
- Aggregate, per-series, and per-segment metrics.
- Forecast-bias and failure-case analysis.
- Probabilistic metrics where a model supports quantiles or samples.
- Runtime and approximate resource-use reporting.

### 3.4 Inventory decision support

- Configurable lead time.
- Configurable service level or forecast quantile.
- Configurable holding, ordering, and lost-sales cost assumptions.
- Restock recommendation based on forecast, safety stock, and inventory position when available.
- Scenario and sensitivity comparison against a historical-average policy.

### 3.5 Application and operations

- Batch forecast command.
- Persisted forecast and recommendation outputs.
- Read-only REST API.
- Local dashboard for overview and SKU-level inspection.
- Health and freshness indicators.
- Basic data, drift, forecast-performance, and pipeline monitoring.
- Containerized local run path.

## 4. Explicitly out of scope

- Forecasting all M5 stores for the first release.
- Online learning or streaming ingestion.
- Point-of-sale write-back.
- Purchase-order execution.
- Customer-level recommendations.
- Dynamic pricing optimization.
- Causal estimation of promotion effects.
- Full supply-chain optimization with capacity and supplier constraints.
- Authentication, billing, organization management, or public multi-user service.
- Automatic model promotion or retraining.
- A custom foundation-model architecture.
- Academic generalization claims about Indonesian UMKM.

## 5. Deliverables

### 5.1 Mandatory

- Reproducible data pipeline.
- Dataset validation report and selection manifest.
- Exploratory analysis report.
- Backtesting and final-test results.
- Model comparison and model card.
- Inventory simulation and sensitivity analysis.
- Local API and dashboard.
- Monitoring report or dashboard section.
- Unit, integration, and smoke tests.
- Container configuration.
- Project README and 6-10 page technical report.
- Two-to-three-minute demo recording or equivalent walkthrough.

### 5.2 Stretch

- Second foundation model.
- Forecast ensemble.
- Explainability views for the global ML model.
- Hosted read-only demo.
- Scheduled local or CI batch job.
- Formal ADI/CV-squared demand taxonomy.

## 6. Definition of done

The MVP is done when mandatory deliverables exist, documented commands work from a clean environment, the final test has been run only after model selection, and the limitations are clearly reported.

The MVP is not blocked merely because the foundation model loses to a baseline. Negative or mixed modeling results are acceptable if the protocol is valid and reproducible.

## 7. Change control

Any proposed addition must be classified as one of:

- mandatory defect fix;
- necessary change to satisfy an acceptance criterion;
- stretch goal;
- post-MVP backlog.

A feature enters the active MVP only if it replaces an existing item of comparable effort or is necessary to complete a stage gate. All other additions remain in the backlog.

## 8. Research extension boundary

The future UMKM study starts only after the portfolio MVP is released. The extension may reuse code but must define a new dataset version, ethics/privacy handling, hypotheses, temporal cutoffs, cost assumptions, and analysis plan.
