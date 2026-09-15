# DemandSense Risk Register

| Field | Value |
|---|---|
| Status | Active from project start |
| Version | 0.5.0 |
| Date | 2026-09-15 |
| Review cadence | Weekly and at every stage gate |

## 1. Scoring

- Probability: Low, Medium, High.
- Impact: Low, Medium, High, Critical.
- Status: Open, Monitoring, Mitigated, Accepted, Closed.

## 2. Active risks

| ID | Risk | Probability | Impact | Trigger / early signal | Prevention / mitigation | Contingency | Status |
|---|---|---|---|---|---|---|---|
| R01 | Target leakage in lag, rolling, imputation, or segmentation logic | Medium | Critical | Validation score is implausibly high; performance collapses on later folds | Shift target features; fit transforms per fold; add cutoff tests; review feature timestamps | Remove affected features, invalidate runs, and rerun all comparisons | Open |
| R02 | Full-store M5 processing exceeds RAM or practical runtime despite sufficient disk | Low | High | Melt/join process swaps, crashes, or exceeds agreed runtime | M1 release preparation completed 5.91 million rows in approximately 10.23 seconds using early store filtering, Polars, and Parquet | Retain partitioned-processing fallback if later feature generation increases memory materially | Mitigated |
| R03 | Foundation-model dependency, checkpoint, or batch size is incompatible with available GPU/VRAM | Low | High | Installation, out-of-memory, or inference failure in later full-store runs | M0 Chronos-Bolt Small inference passed on CUDA; retain batch calibration and pinned environment | Reduce batch size, use CPU fallback, or document omission of the affected stretch model | Mitigated |
| R04 | Public benchmark overlap inflates foundation-model results | Medium | High | Model reports unexpectedly dominant zero-shot performance | Treat M5 as engineering benchmark; disclose possible pretraining overlap; include simple baselines and failure analysis | Avoid novelty claims; later validate on private prospective UMKM data | Monitoring |
| R05 | Development cohort favors easy or high-volume series | Low | High | Cohort results differ materially from the full-store development results | M1 freezes 100 fast, 100 medium, and 100 intermittent series using seed 42 and deterministic within-segment ranking; release reporting remains full-population | Treat cohort findings as engineering-only and base selection on full-population runs | Mitigated |
| R06 | M5 sales zeros are mistaken for zero demand despite unknown stockouts | High | High | Inventory conclusions rely on every zero being true no-demand | State observed-sales limitation; avoid inferred stockout labels; use sensitivity analysis | Limit claims to observed sales and simulated inventory behavior | Accepted |
| R07 | Forecast metric improves but inventory decisions worsen | Medium | High | Challenger wins WRMSSE but has worse stockout/cost metrics | Evaluate decision metrics before champion selection; track bias and quantiles | Use baseline or segment-specific champion; revise decision policy, not test data | Open |
| R08 | Inventory conclusions depend on arbitrary cost assumptions | High | High | Model ranking flips under modest cost changes | Version assumptions and evaluate balanced, shortage-sensitive, and holding-sensitive scenarios | Report conditional conclusions instead of one universal saving estimate | Open |
| R09 | Intermittent-demand metrics become unstable or misleading | Medium | High | Percentage errors are undefined or dominated by near-zero denominators | Use scaled/weighted metrics, document denominators, and report distributions | Remove unsuitable metric from selection policy while retaining it as descriptive | Open |
| R10 | Scope creep delays a complete vertical slice | High | High | New integrations, models, hosting, or UI pages enter active work | Enforce mandatory/stretch/backlog classification and stage gates | Drop stretch items; preserve API, dashboard, tests, and report | Open |
| R11 | Dashboard work begins before output schemas stabilize | Medium | Medium | Repeated UI rewrites and duplicated business logic | Finish forecast and recommendation contracts before Gate C | Use static fixture data until schema is frozen | Open |
| R12 | Final test is inspected repeatedly | Medium | Critical | Hyperparameters or features change after final-test review | Lock test access; record configuration hash; run once after selection | Declare contamination, create a new untouched terminal window if possible | Open |
| R13 | Reproducibility fails across machines | Medium | High | Clean environment cannot repeat core results | Pin dependencies, configure seeds, use small fixtures, add container smoke test | Publish known platform limitation and a verified reference environment | Open |
| R14 | Raw data, model files, or secrets are committed | Low | High | Large/sensitive files appear in Git status | Define `.gitignore`; run secret/large-file checks; document download steps | Remove before sharing; rotate any exposed credential; rewrite history only with explicit approval | Open |
| R15 | Optional hosting consumes time or money before modeling is sound | Medium | Medium | Cloud setup begins before champion and schemas are stable | Hosting remains post-MVP or buffer work; serve cached outputs | Deliver local Docker demo and recorded walkthrough | Accepted |
| R16 | UMKM data is unavailable after portfolio completion | High | Medium | No partner or usable export by research start | Keep M5 portfolio independent; begin outreach separately | End at portfolio MVP or use public benchmark for a clearly labeled replication study | Monitoring |
| R17 | UMKM data contains PII or commercially sensitive fields | Medium | Critical | Names, contacts, addresses, account numbers, or identifiable business details appear | Data-use agreement; minimize collection; pseudonymize; keep raw data private | Stop ingestion, quarantine data, and redesign extraction/anonymization | Open |
| R18 | UMKM timestamps or transaction states have ambiguous meaning | High | High | Order, payment, cancellation, return, and shipment dates are mixed | Create source dictionary with owner; map states explicitly; retain raw status | Aggregate only validated completed transactions and report exclusions | Open |
| R19 | Too little UMKM history for daily SKU forecasting | High | High | Fewer than 12 months or many sparse series | Assess history before research protocol; aggregate to weekly/category level if justified | Reframe study as a limited pilot or continue collecting prospectively | Open |
| R20 | Claims exceed evidence from one store or simulated costs | Medium | Critical | Report language generalizes to all UMKM or claims actual savings | Predefine claim boundaries; distinguish benchmark, case study, and simulation | Revise conclusions and title; add external validation before stronger claims | Open |
| R21 | Kaggle account cannot download M5 files until competition access is accepted | Low | High | Kaggle API returns HTTP 403 on the download endpoint | Official competition rules were accepted and all five files were downloaded successfully on 2026-09-15; retain the documented acquisition command | Reauthenticate and verify rule acceptance on the same Kaggle account; never use an unauthorized mirror | Closed |

## 3. Issue escalation rules

- Critical risks that trigger invalidate affected results until reviewed.
- Any suspected leakage blocks model comparison and champion selection.
- Any privacy incident blocks UMKM ingestion and public release.
- Any change to the locked final-test protocol is recorded as a deviation.
- A stretch goal is removed before extending the mandatory delivery date.

## 4. Weekly risk review

At the end of each week:

1. Review triggers and evidence for all open risks.
2. Update probability, impact, owner, and status.
3. Convert realized risks into tracked issues.
4. Record any protocol or scope deviation.
5. Confirm that the next stage gate remains achievable.

## 5. Risk owners to assign

- [ ] Data and privacy owner.
- [ ] Modeling and evaluation owner.
- [ ] Application and deployment owner.
- [ ] Final release approver.

For a solo project, one person may hold all roles, but the responsibilities should remain explicit.
