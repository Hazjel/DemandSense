# DemandSense M1 Execution Report

| Field | Value |
|---|---|
| Status | Complete |
| Date | 2026-09-15 |
| Schema version | `1.2.0` |
| Eligibility cutoff | `2016-01-31` |
| Segment reference end | `2016-04-24` |
| Blocker | None |

## Outputs

| Profile | Dataset version | Rows | Selected series | Population | Quality |
|---|---|---:|---:|---:|---|
| Smoke | `m5-smoke-3340f709371b` | 58,230 | 30 | 30 | Passed |
| Development | `m5-development-a7ca11c1132f` | 582,300 | 300 | 3,049 | Passed |
| Release | `m5-release-9f701ae20270` | 5,908,404 | 3,044 | 3,049 | Passed |

The development cohort contains exactly 100 fast, 100 medium, and 100
intermittent series. Its series-manifest SHA-256 is
`70735f43edad73f54b91ab847ad1993dde3d1aef1c48eb0a07e8ec16c8c844af`.

The release population contains 131 fast, 1,073 medium, and 1,840 intermittent
series. Five series are excluded at the earliest development cutoff:

- `FOODS_3_595`: no positive sales by the cutoff;
- `FOODS_3_296`: 16 active days;
- `FOODS_2_117`: 37 active days;
- `FOODS_2_209`: 37 active days;
- `FOODS_2_248`: 100 active days.

This report was amended during the M2 pre-freeze audit. Schema 1.1.0 had checked
112 active days at `2016-04-24`, which was too late for development fold 1. Schema
1.2.0 corrects that defect before any benchmark model results were observed. The
release manifest SHA-256 is
`9f4c5b80f0c35a841c40ba6e1880bd4b2c28168b2a6f1d49ddce9e4de1d35092`.

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

- 1,623 release series have an active-period zero run longer than 84 days;
- 57 release series have no positive sale for more than 84 days at the reference end;
- 5,785 release observations exceed the 99.9th-percentile quantity threshold of 48 units;
- 39 release price transitions change by more than 100%;
- canonical missing-price ratio is 18.97%, while active-period missing-price ratio is 0%.

These rows and series remain in the benchmark. M5 sales zeros are observed sales,
not proof of stock availability or latent zero demand.

## Gate decision

**M1 passed after the M2 eligibility audit correction.** The full eligible release dataset, deterministic stratified
development cohort, source fingerprints, version metadata, and quality reports
are available. M2 may define and freeze temporal folds, leakage tests, and the
Seasonal Naive evaluation protocol. The locked final-window targets must not be
used for feature or model selection.
