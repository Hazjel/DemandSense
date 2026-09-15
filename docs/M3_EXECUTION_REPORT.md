# DemandSense M3 Execution Report

| Field | Value |
|---|---|
| Status | Complete |
| Date | 2026-09-15 |
| Suite version | `m3-v1` |
| Run ID | `baseline-f0244fc6ddec` |
| Protocol | `m2-v1` |
| Dataset | `m5-release-9f701ae20270` |
| Population | 3,044 release series |
| Gate decision | Gate B passed |

## Models and evaluation boundary

The suite evaluates four frozen baselines over all three 28-day development
folds:

- `naive_last`: recursive last observation;
- `seasonal_naive_lag_7`: recursive weekly Seasonal Naive;
- `seasonal_naive_lag_28`: recursive four-week Seasonal Naive;
- `croston_sba`: Syntetos-Boylan-adjusted Croston with alpha `0.10`.

Croston starts at each series' frozen `active_start_date`, preventing pre-launch
calendar zeros from inflating its initial demand interval. The suite collected
targets only through `2016-04-24`. It generated no forecast or metric for the
locked-final window beginning `2016-04-25`.

## Metric definitions

- WRMSSE uses each series' mean squared first difference from its first positive
  training observation and observed revenue from the final 28 training days as
  its fold-specific weight. Weights are renormalized within an aggregate or
  reported segment.
- MASE uses the corresponding mean absolute first-difference scale and is averaged
  across valid series.
- WAPE pools absolute errors and observed demand within the reported group.
- Normalized bias pools `forecast - actual`; positive values mean overforecasting.
- A zero denominator is retained as null and counted. No epsilon substitution is
  used.

All 3,044 series had valid RMSSE and MASE scales in every fold. WRMSSE weight
coverage was 100% for every reported aggregate.

## Overall development results

Metrics below are unweighted means of the three fold-level aggregate values.

| Rank | Baseline | Mean WRMSSE | Mean MASE | Mean WAPE | Mean normalized bias |
|---:|---|---:|---:|---:|---:|
| 1 | Croston-SBA | 0.8371 | 0.9939 | 0.8014 | 0.0047 |
| 2 | Seasonal Naive lag 7 | 1.0578 | 1.0523 | 0.8765 | -0.0432 |
| 3 | Seasonal Naive lag 28 | 1.0947 | 1.0704 | 0.8991 | -0.0262 |
| 4 | Last observation | 1.2044 | 1.1980 | 1.0455 | 0.2613 |

Croston-SBA has 20.9% lower mean WRMSSE than the best Seasonal Naive baseline,
lag 7. It ranks first on WRMSSE in every development fold; this is descriptive
development evidence, not a locked-final claim or final champion selection.

## WRMSSE by fold

| Fold | Croston-SBA | Lag 7 | Lag 28 | Last observation |
|---|---:|---:|---:|---:|
| Development 1 | 0.8342 | 1.0627 | 1.0855 | 1.2365 |
| Development 2 | 0.8353 | 1.0393 | 1.1079 | 1.2585 |
| Development 3 | 0.8417 | 1.0715 | 1.0907 | 1.1183 |

## Mean WRMSSE by reporting segment

| Segment | Croston-SBA | Lag 7 | Lag 28 | Last observation |
|---|---:|---:|---:|---:|
| Fast | 0.7544 | 0.9028 | 0.9165 | 1.0781 |
| Medium | 0.8399 | 1.0421 | 1.0799 | 1.2329 |
| Intermittent | 0.8647 | 1.1383 | 1.1825 | 1.2138 |

Intermittent demand remains difficult: its pooled mean WAPE exceeds 1.0 for all
four baselines, and 288, 258, and 185 series respectively have zero actual demand
over the three full fold windows. This is why WRMSSE is primary and WAPE remains
secondary.

## Artifact and integrity evidence

The primary run produced:

- 1,022,784 prediction rows;
- 182,640 per-series/per-horizon-band metric rows;
- 240 aggregate fold/model/segment/band rows;
- zero duplicate prediction keys;
- zero negative forecasts;
- zero rows after `2016-04-24`.

Core artifact SHA-256 values:

| Artifact | SHA-256 |
|---|---|
| Predictions | `1eacd1474ecb159fd22739301a3f61963b6eb6fbab7a7ad7b350c3d736bda8e8` |
| Per-series metrics | `7ea6904901b60ebfa3d5933e9eaa9abe1b1619397bc7702303e2b6c24e57c0b3` |
| Aggregate metrics | `7d02226672fbf2d1c923d3650caba48e26f05fff6849a2e9e0c7a42dbc980f55` |
| Model summary | `8279003e04a31e8bbc197e1373c377f42c60554aa58eb7b7eb798ff854cbd4ef` |

An independent second run produced the same semantic run ID, row counts, and all
four core checksums. Local artifacts are stored under `artifacts/evaluation/m3/`
and `artifacts/evaluation/m3-reproduction/`; both directories are excluded from
Git. The primary measured runtime was approximately 14.74 seconds on the recorded
development workstation.

## Verification

- Ruff: passed.
- Pytest: 23 passed.
- Dependency integrity: checked during the milestone closeout.
- Reproducibility: passed for all core artifacts.
- Locked-final target access: false.
- One upstream Starlette/AnyIO deprecation warning remains non-blocking and is
  unrelated to the evaluator.

## Gate decision

**M3 and Gate B passed.** M4 may evaluate XGBoost and Chronos-Bolt against these
development baselines. Croston-SBA is the current baseline-to-beat, but no model
may be called the final champion until challenger selection is frozen and the
locked-final policy permits its one-time evaluation.
