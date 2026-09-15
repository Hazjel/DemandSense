from __future__ import annotations

import argparse
import json
from pathlib import Path

import polars as pl

from demandsense.config import load_config
from demandsense.data.m5 import M5Adapter
from demandsense.data.validation import validate_canonical
from demandsense.evaluation.protocol import (
    freeze_evaluation_protocol,
    load_evaluation_protocol,
    validate_evaluation_protocol,
)
from demandsense.spikes import format_result, spike_chronos, spike_xgboost


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="demandsense")
    commands = parser.add_subparsers(dest="command", required=True)

    validate_config = commands.add_parser("validate-config")
    validate_config.add_argument("--config", default="configs/smoke.yaml")

    prepare = commands.add_parser("prepare-m5")
    prepare.add_argument("--config", default="configs/smoke.yaml")

    validate_data = commands.add_parser("validate-data")
    validate_data.add_argument("--path", required=True)

    validate_evaluation = commands.add_parser("validate-evaluation")
    validate_evaluation.add_argument("--config", default="configs/evaluation.yaml")

    freeze_evaluation = commands.add_parser("freeze-evaluation")
    freeze_evaluation.add_argument("--config", default="configs/evaluation.yaml")
    freeze_evaluation.add_argument("--output", default="artifacts/evaluation/m2")

    xgboost = commands.add_parser("spike-xgboost")
    xgboost.add_argument("--device", choices=["cpu", "cuda"], default="cuda")

    chronos = commands.add_parser("spike-chronos")
    chronos.add_argument("--model", default="amazon/chronos-bolt-small")
    chronos.add_argument("--horizon", type=int, default=28)
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.command == "validate-config":
        config = load_config(args.config)
        print(json.dumps(config.model_dump(mode="json"), indent=2))
    elif args.command == "prepare-m5":
        result = M5Adapter(load_config(args.config)).prepare()
        print(format_result(result))
    elif args.command == "validate-data":
        report = validate_canonical(pl.read_parquet(Path(args.path)))
        print(format_result(report.to_dict()))
        if report.status != "passed":
            raise SystemExit(1)
    elif args.command == "validate-evaluation":
        report = validate_evaluation_protocol(load_evaluation_protocol(args.config))
        print(format_result(report))
        if report["status"] != "passed":
            raise SystemExit(1)
    elif args.command == "freeze-evaluation":
        print(
            format_result(
                freeze_evaluation_protocol(args.config, args.output)
            )
        )
    elif args.command == "spike-xgboost":
        print(format_result(spike_xgboost(device=args.device)))
    elif args.command == "spike-chronos":
        print(format_result(spike_chronos(args.model, args.horizon)))
