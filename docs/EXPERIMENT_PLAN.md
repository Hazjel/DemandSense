# DemandSense Experiment Plan

| Field | Value |
|---|---|
| Status | Pre-registered project protocol |
| Version | 0.2.0 |
| Date | 2026-09-15 |

## 1. Study purpose

The MVP evaluates whether increasingly complex forecasting methods provide consistent improvements over simple baselines and whether any accuracy improvement translates into lower simulated inventory cost.

The MVP is an engineering benchmark on the full eligible bottom-level population of one selected M5 store. It is not evidence about Indonesian UMKM. A future UMKM study will create a separate protocol version.

## 2. Research questions for the MVP

- **RQ1:** Which model family performs best across the frozen one-store M5 population under rolling temporal evaluation?
- **RQ2:** Does model ranking differ across fast, medium, and intermittent demand?
- **RQ3:** Do better statistical forecast metrics consistently translate into lower simulated inventory cost?
- **RQ4:** What accuracy, latency, and resource trade-offs arise when using a time-series foundation model instead of simpler alternatives?

## 3. Hypotheses

These are testable expectations, not promised outcomes:

- **H1:** The global gradient-boosted model will outperform Seasonal Naive on aggregate when calendar and price features are useful.
- **H2:** A specialized intermittent-demand baseline will remain competitive on zero-heavy series.
- **H3:** The foundation model will not dominate every demand segment.
- **H4:** Ranking by forecast error will differ from ranking by inventory cost under at least one cost scenario.

## 4. Dataset and population freeze

- Source: M5 Forecasting Accuracy data.
- Store: selected during the technical spike, then frozen.
- Release population: every series in the selected store that passes pre-defined eligibility rules.
- Development cohort: target 300 stratified product-store series for fast iteration and configuration pruning.
- Smoke cohort: 30-60 fixed series used only for pipeline validation.
- Segments: fast, medium, and intermittent as defined in `SCOPE.md`.
- Development-cohort selection seed: recorded before tuning.
- All cohort roles and identifiers: persisted in a versioned manifest.
- Exclusions: insufficient history or irreparable data-quality failure only.

No series may be removed from the release population after model results are observed unless the reason is a pre-defined blocking data-quality rule. Any post-result exclusion must be reported as a protocol deviation.

Smoke and development cohorts may accelerate debugging and hyperparameter search. However, reported development-fold comparisons for mandatory models and the locked final test must be rerun on the full eligible release population. A configuration may not be promoted solely because it performs well on the 300-series cohort.

## 5. Temporal evaluation design

Let `T` be the last target date in the frozen evaluation range.

| Split | Training end | Evaluation interval | Use |
|---|---|---|---|
| Development fold 1 | `T-112` | next 28 days | Model development |
| Development fold 2 | `T-84` | next 28 days | Model development |
| Development fold 3 | `T-56` | next 28 days | Model selection |
| Locked final test | `T-28` | final 28 days through `T` | One-time final report |

Rules:

- Random train/test splitting is prohibited.
- The final-test targets are not inspected during feature or hyperparameter decisions.
- Hyperparameters are selected from development folds only.
- Final models may train through `T-28` after the configuration is frozen.
- Mandatory model comparisons use the frozen release population; smaller cohorts are labeled engineering runs.
- All models receive equivalent target history subject to declared model context limits.
- Known-future features must be marked and justified.

## 6. Model matrix

### 6.1 Mandatory models

| ID | Family | Model | Purpose |
|---|---|---|---|
| B1 | Naive | Last observation | Sanity lower bound |
| B2 | Seasonal naive | Lag 7 | Weekly baseline |
| B3 | Seasonal naive | Lag 28 | Four-week baseline |
| B4 | Intermittent | Croston/SBA | Zero-heavy demand baseline |
| C1 | Global ML | LightGBM or XGBoost | Covariate-aware challenger |
| F1 | Foundation | Chronos, smallest viable checkpoint | Zero-shot foundation-model challenger |

### 6.2 Stretch models

- ETS or auto-ETS on viable series.
- TimesFM.
- Equal-weight or development-weighted ensemble.
- A model selected separately per demand segment.

Stretch models cannot delay mandatory documentation, testing, and application delivery.

## 7. Feature plan for the global ML model

Target-derived features:

- lags: 1, 7, 14, 28, and 56 days;
- rolling mean: 7, 28, and 56 days;
- rolling standard deviation: 7, 28, and 56 days;
- non-zero rate and days since last non-zero sale;
- expanding mean where computationally practical.

Known or source features:

- day of week, week, month, weekend;
- event name and event type;
- SNAP eligibility;
- price, price change, and relative price within the same SKU-store history.

Leakage safeguards:

- All target rolling features are shifted before aggregation.
- Encoders and imputers are fitted inside each training fold.
- Price-derived future features are allowed only when the price is treated as known at forecast time; otherwise they are lagged.
- The exact feature list and availability assumption are stored in the run configuration.

## 8. Metrics

### 8.1 Primary forecast metric

- M5-aligned revenue-weighted RMSSE computed on the frozen one-store bottom-level population, labeled `weighted_rmsse_store_bottom_level` to avoid implying the full competition hierarchy.

### 8.2 Secondary forecast metrics

- MASE.
- WAPE, with denominator and zero-demand behavior documented.
- Mean signed error or normalized bias.
- Per-horizon error for days 1-7, 8-14, 15-21, and 22-28.
- Runtime and peak memory where measurable.

### 8.3 Probabilistic metrics

When forecasts provide samples or quantiles:

- pinball loss for selected quantiles;
- empirical coverage of prediction intervals;
- interval width.

Point-only models are not assigned fabricated probabilistic scores.

### 8.4 Inventory metrics

- total units ordered;
- average inventory;
- stockout days;
- lost units or lost-sales proxy;
- fill rate/service level;
- holding cost;
- ordering cost;
- lost-sales cost;
- total simulated cost.

## 9. Inventory scenarios

At minimum, evaluate:

- balanced shortage and holding penalties;
- shortage-sensitive scenario;
- holding-cost-sensitive scenario.

All costs, lead times, initial inventory, and replenishment rules are stored as a versioned `assumption_set_id`. M5 lacks true inventory state, so results must be labeled simulations rather than observed savings.

## 10. Model-selection policy

A challenger is eligible to become champion when it:

1. improves the primary development metric by at least 5% relative to the best mandatory seasonal-naive baseline;
2. wins on at least two of three development folds;
3. does not degrade the intermittent segment by more than 3% relative to its best mandatory baseline, unless a segment-specific champion is used;
4. shows no unacceptable systematic underforecast bias;
5. improves or remains competitive on total inventory cost in the balanced scenario;
6. satisfies runtime and operational constraints.

If no challenger qualifies, the most stable eligible baseline becomes champion. Thresholds may be revised only before full development-fold results are reviewed, with the reason recorded.

## 11. Statistical analysis

- Report fold-level and series-level distributions, not only means.
- Use paired bootstrap confidence intervals over matched series/fold errors for key model differences.
- Where formal pairwise tests are added, correct for multiple comparisons.
- Report effect sizes and uncertainty alongside p-values.
- Perform sensitivity analysis for inventory cost ratios and lead time.
- Analyze representative failure cases from each demand segment.

## 12. Experiment tracking

Every run records:

```text
run_id
git_commit
dataset_version
schema_version
selection_manifest_version
fold_id
cutoff_date
model_name
model_version
hyperparameters
feature_set_version
random_seed
metrics
runtime
peak_memory_if_available
artifact_locations
run_status
failure_reason
```

Failed runs are retained in the experiment log.

## 13. Required ablations

For the global ML model:

- lag-only features versus lag plus calendar;
- lag plus calendar versus all permitted price/event features.

For the final decision analysis:

- model ranking by forecast metric;
- model ranking by inventory cost;
- results with and without intermittent-series stratification.

## 14. Known validity threats

- M5 is not an Indonesian UMKM dataset.
- Public benchmark data may overlap with foundation-model pretraining data.
- M5 has observed sales but no stock-on-hand or explicit stockout labels.
- The one-store population limits external validity across stores, regions, datasets, and business types.
- Inventory costs and initial stock are simulated assumptions.
- Known-future price availability may not reflect every real business workflow.

These threats must appear in the final report and model card.

## 15. Research extension protocol

A future Indonesian UMKM study should add separate questions covering data scarcity, exogenous covariates, intermittent demand, prospective performance, and economic utility. It must use a new protocol document rather than silently modifying this benchmark protocol.
