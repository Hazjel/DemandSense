# DemandSense

DemandSense is a leakage-safe demand-forecasting and inventory decision-support project. The portfolio release uses M5 data, compares simple baselines, XGBoost, and a pretrained time-series foundation model, then evaluates the downstream inventory implications.

**M0 through M3 and Gate B are complete; M4 (challenger models) is next.** Four mandatory baselines have been evaluated reproducibly over all three development folds and 3,044 eligible `CA_1` series. The locked-final targets remain untouched. Research claims about Indonesian UMKM remain explicitly out of scope until a separate dataset and protocol are available.

Current schema `1.2.0` datasets:

- release: `m5-release-9f701ae20270` with 3,044 eligible series;
- development: `m5-development-a7ca11c1132f` with 300 frozen series;
- smoke: `m5-smoke-3340f709371b` with 30 fixed series.

## Prerequisites

- Python 3.12
- NVIDIA GPU with a working CUDA driver for GPU experiments
- Docker Desktop with Docker Compose for the optional container path
- Kaggle account with the M5 competition rules accepted

## Local setup with pip and venv

PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
```

`requirements.lock` is the reproduced M0 environment, including the CUDA 12.1 PyTorch wheel. `requirements-dev.txt` contains the direct dependency specification used when intentionally resolving a new lock.

Validate the environment:

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
```

## Data acquisition

The raw M5 files belong under `data/raw/m5/` and are excluded from Git.

```powershell
kaggle competitions download -c m5-forecasting-accuracy -p data/raw/m5
Expand-Archive -LiteralPath data/raw/m5/m5-forecasting-accuracy.zip -DestinationPath data/raw/m5
```

Required files:

- `calendar.csv`
- `sales_train_evaluation.csv` or `sales_train_validation.csv`
- `sell_prices.csv`

## M0 and data-validation commands

```powershell
# Configuration check
.\.venv\Scripts\python.exe -m demandsense validate-config --config configs/smoke.yaml

# Prepare the fixed smoke cohort as canonical Parquet
.\.venv\Scripts\python.exe -m demandsense prepare-m5 --config configs/smoke.yaml

# Prepare the stratified 300-series development cohort
.\.venv\Scripts\python.exe -m demandsense prepare-m5 --config configs/base.yaml

# Prepare the full eligible CA_1 release population
.\.venv\Scripts\python.exe -m demandsense prepare-m5 --config configs/portfolio.yaml

# Revalidate a generated canonical table
.\.venv\Scripts\python.exe -m demandsense validate-data --path data/processed/m5/smoke/demand_daily.parquet

# Verify XGBoost can train on CUDA
.\.venv\Scripts\python.exe -m demandsense spike-xgboost

# Download and test the small Chronos-Bolt checkpoint
.\.venv\Scripts\python.exe -m demandsense spike-chronos
```

Each profile output includes `dataset_metadata.json`, `quality_report.json`, a
versioned series manifest, source checksums, and canonical validation evidence
under `data/processed/m5/{profile}/`.

## Frozen M2 evaluation protocol

```powershell
# Validate dataset identity, fold boundaries, active-history eligibility, and leakage policy
.\.venv\Scripts\python.exe -m demandsense validate-evaluation --config configs/evaluation.yaml

# Materialize the local freeze evidence (artifacts are intentionally excluded from Git)
.\.venv\Scripts\python.exe -m demandsense freeze-evaluation --config configs/evaluation.yaml --output artifacts/evaluation/m2
```

The versioned source of truth is `configs/evaluation.yaml`. It fixes three
development folds, one locked final fold, reporting-only segments, lagged target
features, fold-local transforms, lagged-only future prices, and recursive
Seasonal Naive behavior.

## M3 baseline suite

```powershell
# Run all four baselines on the full release population and development folds
.\.venv\Scripts\python.exe -m demandsense run-baselines --config configs/baselines.yaml --output artifacts/evaluation/m3

# Re-run independently and require identical core artifact checksums
.\.venv\Scripts\python.exe -m demandsense verify-baselines --config configs/baselines.yaml --reference artifacts/evaluation/m3 --output artifacts/evaluation/m3-reproduction
```

Run `baseline-f0244fc6ddec` evaluates last observation, Seasonal Naive lag 7,
Seasonal Naive lag 28, and Croston-SBA. Croston-SBA is the strongest development
baseline with mean WRMSSE `0.8371`; this is a baseline result, not the final
champion decision. Generated predictions and metric tables remain local under
`artifacts/` and are excluded from Git.

## Docker

The API and dashboard use the same image but run as separate Compose services:

```powershell
docker compose config
docker compose up --build
```

- API: <http://127.0.0.1:8000/health>
- Dashboard: <http://127.0.0.1:8501>

## Documentation

Start with [`docs/PROJECT_CHARTER.md`](docs/PROJECT_CHARTER.md), then read [`docs/SCOPE.md`](docs/SCOPE.md), [`docs/DATA_CONTRACT.md`](docs/DATA_CONTRACT.md), [`docs/M3_EXECUTION_REPORT.md`](docs/M3_EXECUTION_REPORT.md), and [`docs/EXPERIMENT_PLAN.md`](docs/EXPERIMENT_PLAN.md).
