# DemandSense

DemandSense is a leakage-safe demand-forecasting and inventory decision-support project. The portfolio release uses M5 data, compares simple baselines, XGBoost, and a pretrained time-series foundation model, then evaluates the downstream inventory implications.

**M0, Gate A, and M1 are complete; M2 (evaluation design) is next.** The full eligible `CA_1` release population and the frozen stratified development cohort pass raw, canonical, manifest, and quality validation. Research claims about Indonesian UMKM remain explicitly out of scope until a separate dataset and protocol are available.

Current schema `1.1.0` datasets:

- release: `m5-release-5429af493bf1` with 3,047 eligible series;
- development: `m5-development-5651b48df83f` with 300 frozen series;
- smoke: `m5-smoke-5d3455693411` with 30 fixed series.

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

## Docker

The API and dashboard use the same image but run as separate Compose services:

```powershell
docker compose config
docker compose up --build
```

- API: <http://127.0.0.1:8000/health>
- Dashboard: <http://127.0.0.1:8501>

## Documentation

Start with [`docs/PROJECT_CHARTER.md`](docs/PROJECT_CHARTER.md), then read [`docs/SCOPE.md`](docs/SCOPE.md), [`docs/DATA_CONTRACT.md`](docs/DATA_CONTRACT.md), [`docs/M1_EXECUTION_REPORT.md`](docs/M1_EXECUTION_REPORT.md), and [`docs/EXPERIMENT_PLAN.md`](docs/EXPERIMENT_PLAN.md).
