# DemandSense M1 Execution Report

| Field | Value |
|---|---|
| Status | Complete |
| Date | 2026-09-15 |
| Schema version | `1.1.0` |
| Reference end | `2016-04-24` |
| Blocker | None |

## Outputs

| Profile | Dataset version | Rows | Selected series | Population | Quality |
|---|---|---:|---:|---:|---|
| Smoke | `m5-smoke-5d3455693411` | 58,230 | 30 | 30 | Passed |
| Development | `m5-development-5651b48df83f` | 582,300 | 300 | 3,049 | Passed |
| Release | `m5-release-5429af493bf1` | 5,914,227 | 3,047 | 3,049 | Passed |

The development cohort contains exactly 100 fast, 100 medium, and 100
intermittent series. Its series-manifest SHA-256 is
`983fec1c4081d7a53a901916da8425c6b1279c7029eac5c459678f263c11a819`.

The release population contains 131 fast, 1,073 medium, and 1,843 intermittent
series. Two series are excluded for insufficient active history:

- `FOODS_3_296`: 100 active days;
- `FOODS_3_595`: 72 active days.

No series is excluded solely for sparse demand, missing price before launch, or
an inactive tail.

## Blocking validation

All profiles pass raw-source, canonical-table, series-manifest, and quality
validation. The release checks report:

- zero duplicate source IDs, calendar days, and price keys;
- zero missing source day-to-calendar mappings;
- zero duplicate canonical keys, negative quantities, or null required values;
- zero non-finite quantities or prices and zero non-positive present prices;
- zero incomplete selected series and zero category instability;
- zero event-label semantic mismatches;
- exact agreement between selected manifest keys and canonical rows.

## Investigated warnings

Warnings remain visible and do not change the passing quality status:

- 1,622 release series have an active-period zero run longer than 84 days;
- 57 release series have no positive sale for more than 84 days at the reference end;
- 5,785 release observations exceed the 99.9th-percentile quantity threshold of 48 units;
- 39 release price transitions change by more than 100%;
- canonical missing-price ratio is 19.04%, while active-period missing-price ratio is 0%.

These rows and series remain in the benchmark. M5 sales zeros are observed sales,
not proof of stock availability or latent zero demand.

## Gate decision

**M1 passed.** The full eligible release dataset, deterministic stratified
development cohort, source fingerprints, version metadata, and quality reports
are available. M2 may define and freeze temporal folds, leakage tests, and the
Seasonal Naive evaluation protocol. The locked final-window targets must not be
used for feature or model selection.
