# DemandSense Data Contract

| Field | Value |
|---|---|
| Status | Accepted M0 contract |
| Version | 1.1.0 |
| Date | 2026-09-15 |
| Canonical grain | One row per date, store, and SKU |

## 1. Contract principles

- Source-specific logic belongs in adapters.
- Downstream features and models consume only canonical tables.
- Observed sales are not always equal to latent demand.
- Data available after a forecast cutoff must never influence features at or before that cutoff.
- Raw data is immutable and excluded from Git.
- Every processed dataset has a version, source fingerprint, schema version, and creation timestamp.

## 2. Source files for the M5 adapter

Expected M5 inputs:

- `sales_train_validation.csv` or `sales_train_evaluation.csv`
- `calendar.csv`
- `sell_prices.csv`

Optional competition files such as sample submissions are not canonical inputs.

## 3. Canonical demand table

Table name: `demand_daily`

| Column | Type | Required | Constraint | Meaning |
|---|---|---:|---|---|
| `date` | date | Yes | Non-null | Local business date |
| `store_id` | string | Yes | Non-empty | Stable anonymized store identifier |
| `sku_id` | string | Yes | Non-empty | Stable anonymized product identifier |
| `category` | string | Yes | Non-empty | Highest useful product category |
| `subcategory` | string | No |  | Department or lower-level grouping |
| `quantity_sold` | float | Yes | `>= 0` | Units observed as sold on the date |
| `unit_price` | float | No | `> 0` when present | Selling price per unit |
| `promotion_flag` | boolean | No |  | Explicit promotion active on date |
| `event_flag` | boolean | No |  | Calendar or special event indicator |
| `event_name` | string | No |  | Event label when available |
| `snap_eligible` | boolean | No |  | M5 SNAP-program eligibility for store/date |
| `stock_on_hand` | float | No | `>= 0` when present | Closing or pre-sale stock, definition recorded by source |
| `stockout_flag` | boolean | No |  | Evidence that sales may be censored by unavailable stock |
| `unit_cost` | float | No | `>= 0` when present | Acquisition or production cost per unit |
| `source` | string | Yes | Enum-like | For example `m5` or `umkm_partner` |
| `ingested_at` | timestamp | Yes | Non-null | UTC ingestion timestamp |

Primary key:

```text
(date, store_id, sku_id)
```

## 4. M5-to-canonical mapping

| Canonical column | M5 source | Rule |
|---|---|---|
| `date` | `calendar.date` | Join M5 day key `d` to calendar |
| `store_id` | sales `store_id` | Direct |
| `sku_id` | sales `item_id` | Direct |
| `category` | sales `cat_id` | Direct |
| `subcategory` | sales `dept_id` | Direct |
| `quantity_sold` | melted `d_1...d_n` values | Convert wide daily columns to long rows |
| `unit_price` | `sell_prices.sell_price` | Join on `store_id`, `item_id`, and `wm_yr_wk` |
| `promotion_flag` | unavailable | Null; do not infer promotion solely from price changes |
| `event_flag` | calendar event fields | True when an event name is present |
| `event_name` | `event_name_1`, `event_name_2` | Preserve both using a documented delimiter or normalized event table |
| `snap_eligible` | state-specific SNAP column | Select the state column matching the store |
| `stock_on_hand` | unavailable | Null |
| `stockout_flag` | unavailable | Null |
| `unit_cost` | unavailable | Null |
| `source` | constant | `m5` |

Absence of sales must not be labeled a stockout when inventory evidence is unavailable.

## 5. Supporting tables

### 5.1 Series manifest

Table name: `series_manifest`

| Column | Meaning |
|---|---|
| `dataset_version` | Processed dataset identifier |
| `store_id` | Selected store |
| `sku_id` | Selected product |
| `segment` | `fast`, `medium`, or `intermittent` |
| `zero_sales_ratio` | Ratio used for MVP segmentation |
| `history_days` | Available history length |
| `selection_seed` | Sampling seed |
| `cohort_role` | One or more of `smoke`, `development`, or `release` |
| `included` | Whether series is in the frozen release population |
| `exclusion_reason` | Reason when excluded |
| `eligible` | Whether the series passes frozen history and activity rules |
| `reference_end_date` | Last date allowed to define eligibility and cohort segment |
| `reference_history_days` | Calendar rows available through the reference end |
| `active_start_date` | First positive sale or available price |
| `active_history_days` | Days from active start through the reference end |
| `last_positive_date` | Last positive sale within the reference window |
| `trailing_zero_days` | Days since the last positive sale at the reference end |
| `total_sales` | Observed units sold within the reference window |
| `missing_price_ratio` | Missing-price ratio across the full reference window |
| `active_missing_price_ratio` | Missing-price ratio on or after active start |

### 5.2 Forecast output

Table name: `forecast_daily`

| Column | Type | Meaning |
|---|---|---|
| `forecast_run_id` | string | Unique run identifier |
| `cutoff_date` | date | Last observation available to the model |
| `forecast_date` | date | Predicted date |
| `store_id` | string | Store identifier |
| `sku_id` | string | Product identifier |
| `model_name` | string | Producing model |
| `point_forecast` | float | Non-negative expected/median units, definition documented |
| `q10` | float, optional | 10th percentile |
| `q50` | float, optional | Median |
| `q90` | float, optional | 90th percentile |
| `generated_at` | timestamp | UTC generation time |
| `model_version` | string | Model artifact version |
| `dataset_version` | string | Input dataset version |

Forecast outputs must be clipped at zero only as an explicit post-processing step recorded in the run configuration.

### 5.3 Inventory recommendation output

Table name: `inventory_recommendation`

| Column | Meaning |
|---|---|
| `recommendation_run_id` | Unique recommendation identifier |
| `forecast_run_id` | Source forecast run |
| `as_of_date` | Decision date |
| `store_id`, `sku_id` | Series identifiers |
| `lead_time_days` | Assumed replenishment lead time |
| `inventory_position` | On-hand plus on-order minus backorders, when available |
| `forecast_during_lead_time` | Expected/selected-quantile demand |
| `safety_stock` | Configured uncertainty buffer |
| `recommended_order_qty` | Non-negative proposed quantity |
| `policy_name` | Decision policy identifier |
| `assumption_set_id` | Versioned cost and service assumptions |

For M5, actual inventory position is unavailable. The simulator must initialize or synthesize inventory under a documented policy and label recommendations as simulated.

## 6. Validation rules

### 6.1 Blocking rules

- Canonical primary key is unique.
- Required columns are present with compatible types.
- `quantity_sold` is finite and non-negative.
- Dates fall within the declared dataset range.
- No selected series has duplicate or unordered dates after canonicalization.
- All fold cutoffs occur after the minimum required history.
- Feature timestamps do not exceed their associated forecast cutoff.

### 6.2 Warning rules

- Missing-price rate exceeds the configured threshold.
- A series contains long zero runs.
- A series begins late or becomes inactive.
- Extreme quantity or price changes are detected.
- Category mappings change across the same SKU.
- Expected calendar events fail to join.

Warnings are reported and investigated; they are not silently imputed away.

M1 warning thresholds are configuration-controlled: 25% active global missing
price, 75% active per-series missing price, zero runs longer than 84 days,
inactive tails longer than 84 days, quantities above the 99.9th percentile, and
absolute week-to-week price changes greater than 100%. Warnings do not change a
passing status unless a blocking rule also fails.

## 7. Missing-value policy

- Missing sales rows are not automatically equivalent to zero sales.
- M5 daily sales cells present as zero remain observed zeros.
- Missing prices may be carried forward only within the same store-SKU and only under a documented rule.
- Unknown optional fields remain null; do not fabricate stock, cost, or promotion labels in the canonical table.
- Models that cannot accept missing values receive transformations inside their model pipeline, fitted only on training data.

## 8. Leakage boundary

For a prediction with cutoff date `C`:

- target-derived lags and rolling statistics may use dates `<= C` only;
- price or calendar features after `C` may be used only if they are legitimately known at decision time;
- global encoders and imputers are fitted using the training portion only;
- segmentation for comparative reporting should use training history for each fold or a separately frozen pre-test reference period;
- the locked final-test target values must not influence feature design or model selection.

## 9. Dataset versioning

Every processed dataset version records:

```text
schema_version
source_name
source_file_checksums
adapter_version or git_commit
creation_timestamp
selected_store
selection_seed
cohort_definition_version
smoke_cohort_manifest_checksum
development_cohort_manifest_checksum
selected_series_manifest_checksum
date_range
row_count
validation_status
```

The record is persisted as `dataset_metadata.json`, while detailed blocking checks,
raw-source checks, profiles, and investigated warnings are persisted as
`quality_report.json`. M5 version identifiers use
`m5-{profile}-{12-character digest}`, where the digest covers schema and adapter
versions, source checksums, selected store, cohort settings, seed, and segmentation
thresholds. The identifier therefore remains stable when the same inputs and
configuration are reproduced.

## 10. UMKM extension and privacy

An UMKM adapter must output the same canonical tables. Before ingestion:

- obtain documented permission from the data owner;
- remove names, phone numbers, addresses, account numbers, and customer identifiers;
- replace business, store, and SKU identifiers when disclosure is not authorized;
- document the meaning and timing of stock fields;
- distinguish cancellations, returns, and refunds from negative demand;
- document whether timestamps reflect order, payment, shipment, or completion time;
- store raw private data outside the public repository;
- publish only aggregated or anonymized derivatives allowed by the agreement.
