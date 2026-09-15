# DemandSense Project Charter

| Field | Value |
|---|---|
| Status | M2 complete; M3 ready |
| Version | 0.7.0 |
| Date | 2026-09-15 |
| Owner | Repository owner (personal name pending for public release) |
| Delivery target | Portfolio MVP in 8 weeks, with 2 optional buffer weeks |

## 1. Purpose

DemandSense is a demand-forecasting and inventory decision-support project. It predicts daily product demand for the next 28 days, compares classical forecasting, machine-learning, and time-series foundation models, and translates forecasts into transparent stock recommendations.

The first release is a reproducible local portfolio project. It is intentionally designed so that a later study can replace the M5 benchmark data with Indonesian MSME (UMKM) transaction data without rebuilding the experiment engine.

## 2. Problem statement

Inventory decisions based only on intuition or recent averages can create two costly outcomes:

- stockouts and lost sales when stock is too low;
- excess inventory and holding cost when stock is too high.

Forecasting accuracy alone is not sufficient. DemandSense must evaluate whether a forecast improves the downstream inventory decision and must disclose where the model is unreliable.

## 3. Primary user

The primary user for the MVP is an inventory planner or small-business owner who needs to answer:

1. How many units are likely to be needed over the next 28 days?
2. How uncertain is the forecast?
3. Which products have elevated stockout or excess-stock risk?
4. Which forecasting model is currently trusted, and why?

## 4. Objectives

### 4.1 Mandatory objectives

- Build a reproducible pipeline from raw M5 data to evaluated forecasts.
- Compare at least four model families under leakage-safe temporal validation.
- Report performance by demand segment, not only as one aggregate score.
- Convert forecasts into inventory recommendations using explicit cost assumptions.
- Expose saved forecasts and recommendations through a local API and dashboard.
- Provide tests, configuration, experiment tracking, monitoring checks, and documentation.

### 4.2 Research-readiness objective

- Isolate source-specific ingestion behind data adapters.
- Use a canonical data contract shared by M5 and future UMKM data.
- Preserve experiment configurations, dataset versions, model artifacts, and results.
- Keep benchmark conclusions separate from later claims about Indonesian UMKM.

## 5. Success criteria

The MVP is complete when all of the following are true:

- Raw-to-processed data preparation runs through a documented command.
- Dataset validation and leakage checks pass.
- Seasonal Naive, an intermittent-demand method, a global ML model, and one time-series foundation model are evaluated.
- Three development folds and one locked final test window are reported.
- Metrics are available globally, by SKU, and by demand segment.
- An inventory simulation reports stockouts, service level, excess stock, and total assumed cost.
- A model is selected using a documented champion policy; selecting a simple baseline is allowed.
- A local API and dashboard read persisted forecast results successfully.
- Automated unit, integration, and smoke tests pass.
- The project can be started locally with documented commands and a containerized path.
- Limitations, failed experiments, and reproducibility information are documented.

## 6. Non-goals for the MVP

- Real-time event streaming.
- Mobile application development.
- Marketplace, payment, or POS integrations.
- Automatic purchasing or financial transactions.
- Automatic retraining without human approval.
- Multi-tenant authentication and authorization.
- Kubernetes, microservices, or high-availability infrastructure.
- Claims that M5 results generalize to Indonesian UMKM.
- Training a time-series foundation model from scratch.

## 7. Constraints

- Development is assumed to be performed by one person for 10-15 hours per week.
- The MVP should run locally; paid hosting is not required.
- Training and forecast generation may be batch operations.
- Local storage and a GPU are available; exact RAM, free disk, GPU model, and VRAM must be recorded during Gate A.
- The release benchmark should fit on the local workstation without requiring paid cloud compute.
- Raw datasets, model weights, secrets, and large artifacts must not be committed to Git.

## 8. Working assumptions

- M5 is the initial engineering benchmark.
- The MVP uses one selected store and includes every eligible product-store series in the release benchmark.
- A stratified cohort of approximately 300 series is used only for rapid development and tuning; it is not the final evaluation population.
- The forecast horizon is 28 daily periods.
- Development diagnostics remain stratified across fast, medium, and intermittent demand.
- Saved forecasts are served to the dashboard; expensive models do not run on every page request.
- Inventory costs in the MVP are scenario assumptions, not audited business costs.

## 9. Delivery milestones

| Milestone | Target | Exit condition |
|---|---:|---|
| M0: Planning and technical spike | Pre-week / 1-2 days | **Complete:** GPU inference and the real-data M5 smoke pipeline pass |
| M1: Validated dataset | Week 1 | **Complete:** full eligible dataset, frozen development cohort, and quality reports available |
| M2: Evaluation design | Week 2 | **Complete:** temporal folds, segments, metrics, and leakage policy frozen |
| M3: Baseline suite | Week 3 | Naive, statistical, and intermittent baselines evaluated |
| M4: Challenger models | Weeks 4-5 | Global ML and at least one foundation model evaluated |
| M5: Decision layer | Week 6 | Inventory simulation and sensitivity analysis available |
| M6: Application layer | Week 7 | Local API, dashboard, and monitoring checks operational |
| M7: Portfolio release | Week 8 | Tests, container, README, report, and demo completed |
| Buffer and hosting | Weeks 9-10, optional | Reliability fixes and optional hosted demo |

## 10. Stage gates

### Gate A: Start full implementation

- [x] Project scope is accepted.
- [x] Dataset access is confirmed through the official Kaggle competition.
- [x] CPU, RAM, GPU model, VRAM, free disk, and driver/runtime compatibility are recorded.
- [x] XGBoost CUDA, Chronos-Bolt CUDA, and real M5 smoke-pipeline spikes succeed.

Gate A passed on 2026-09-15. Evidence is recorded in `M0_EXECUTION_REPORT.md`.

### Gate B: Start advanced modeling

- [x] Data validation passes.
- [x] Temporal folds are frozen.
- [ ] Seasonal Naive results are reproducible on the full release benchmark (M3).
- [x] M2 protocol and recursive-baseline leakage tests pass.

Gate B is not yet passed. M3 may implement and run the baseline suite, but advanced
challenger modeling remains gated until the full Seasonal Naive results are saved
and reproduced.

### Gate C: Start application work

- Champion-selection inputs are available.
- Forecast and recommendation output schemas are stable.
- Batch inference can persist artifacts reliably.

### Gate D: Release

- Definition of done is satisfied.
- Known limitations and risks are documented.
- A clean-environment run or container smoke test succeeds.

## 11. Open decisions

These decisions must be recorded before Gate A:

- [x] Owner role assigned to the repository owner; personal name may be added before public release.
- [x] Local GPU and sufficient storage availability confirmed by the project owner.
- [x] Hardware recorded: i7-12700H, 23.63 GB RAM, RTX 3060 Laptop GPU with 6 GB VRAM, and 235.58 GB free on drive D at the final M0 audit.
- [x] Initial M5 store fixed as `CA_1` before model results are observed.
- [x] Seed fixed at `42`; zero-sales thresholds fixed at `0.20` and `0.60`.
- [x] Local release is mandatory; hosted demo remains optional buffer work.
- [x] TimesFM is a stretch model; Chronos-Bolt Small is the mandatory foundation challenger.

## 12. Future research extension

The portfolio release answers whether the system can be engineered and evaluated reproducibly. It does not answer whether the findings hold for Indonesian UMKM.

A research extension will require new UMKM data, a renewed literature review, revised hypotheses, repeated experiments, statistical analysis, privacy review, and appropriately limited conclusions. The M5-trained model and M5 conclusions are not carried over as evidence; only the reusable pipeline and evaluation protocol are carried over.
