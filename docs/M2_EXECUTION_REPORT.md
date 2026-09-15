# DemandSense M2 Execution Report

| Field | Value |
|---|---|
| Status | Complete |
| Date | 2026-09-15 |
| Protocol version | `m2-v1` |
| Release dataset | `m5-release-9f701ae20270` |
| Schema | `1.2.0` |
| Blocker | None for M2; Gate B awaits M3 baseline results |

## Frozen design

M2 freezes three consecutive 28-day development folds and one locked final
28-day test. The versioned source of truth is `configs/evaluation.yaml`.

| Fold | Training end | Evaluation window | Access |
|---|---|---|---|
| `development_1` | 2016-01-31 | 2016-02-01 to 2016-02-28 | Development |
| `development_2` | 2016-02-28 | 2016-02-29 to 2016-03-27 | Development |
| `development_3` | 2016-03-27 | 2016-03-28 to 2016-04-24 | Model selection |
| `locked_final` | 2016-04-24 | 2016-04-25 to 2016-05-22 | Locked until champion freeze |

The protocol also freezes the primary and secondary metrics, four weekly horizon
bands, zero-denominator handling, RMSSE scale and weighting windows, and recursive
Seasonal Naive lags 1, 7, and 28.

## Eligibility defect found and corrected

The pre-freeze audit found that schema 1.1.0 measured the 112-day active-history
rule at `2016-04-24`. That allowed three additional late-start series into the
earliest development fold. Schema 1.2.0 now measures eligibility at `2016-01-31`.
Five series are excluded, leaving 3,044 eligible release series. This correction
was made before any baseline or challenger benchmark result was observed.

## Leakage controls verified

The validation command passed every frozen check:

- dataset version, schema, manifest checksum, date coverage, and series count match;
- every included series has at least 112 active days at every fold cutoff;
- development evaluation windows end before the locked final window;
- segments are reporting-only and unavailable as model features;
- target features require lag one or greater;
- transformations are fitted on fold-training data only;
- future price features are lagged-only;
- Seasonal Naive is recursive beyond the cutoff.

Protocol validation scans only `date`, `store_id`, and `sku_id` from the canonical
demand table. Its evidence records `target_columns_read: []` and
`final_target_values_accessed: false`.

## Verification evidence

- Ruff: passed.
- Pytest: 19 passed; one upstream Starlette/AnyIO deprecation warning is non-blocking.
- Protocol validation: passed, including zero short-history series in all folds.
- Local freeze artifacts: generated under `artifacts/evaluation/m2/` and excluded from Git.
- Series manifest SHA-256: `9f4c5b80f0c35a841c40ba6e1880bd4b2c28168b2a6f1d49ddce9e4de1d35092`.
- Protocol JSON SHA-256: `7fe03e47272b321d5da3082c5b0136a25d23d7e8b9d62f7f53685a8ad7ceb74a`.
- Temporal-fold Parquet SHA-256: `41a4cf265a45f5170710f51dacbe561f73591f30bc63079800a50d846f0b21a4`.
- Leakage report SHA-256: `578b76a3b8333b313c342eef3ecdd472f7fbbfed5e3f25e4ac923f55ceb6740f`.

## Gate decision

**M2 passed.** M3 may implement and execute the full baseline suite. Gate B is
deliberately not marked complete yet: the recursive Seasonal Naive utility and
its leakage test exist, but reproducible full-release benchmark results belong to
M3 and have not been produced or inspected in M2.
