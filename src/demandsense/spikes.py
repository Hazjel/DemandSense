from __future__ import annotations

import json
import time
from typing import Any

import numpy as np


def spike_xgboost(device: str = "cuda", seed: int = 42) -> dict[str, Any]:
    import xgboost as xgb

    rng = np.random.default_rng(seed)
    features = rng.normal(size=(2_000, 16)).astype(np.float32)
    target = (2 * features[:, 0] - features[:, 1] + rng.normal(0, 0.1, 2_000)).astype(
        np.float32
    )
    started = time.perf_counter()
    model = xgb.XGBRegressor(
        n_estimators=10,
        max_depth=4,
        learning_rate=0.1,
        tree_method="hist",
        device=device,
        random_state=seed,
    )
    model.fit(features, target)
    booster = model.get_booster()
    booster.set_param({"device": "cpu"})
    predictions = booster.inplace_predict(features[:10])
    return {
        "status": "passed",
        "device": device,
        "xgboost_version": xgb.__version__,
        "runtime_seconds": round(time.perf_counter() - started, 4),
        "prediction_count": int(predictions.size),
    }


def spike_chronos(
    model_id: str = "amazon/chronos-bolt-small",
    prediction_length: int = 28,
) -> dict[str, Any]:
    import torch
    from chronos import ChronosBoltPipeline

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is not available to PyTorch")
    context = torch.arange(1, 129, dtype=torch.float32).repeat(2, 1)
    started = time.perf_counter()
    pipeline = ChronosBoltPipeline.from_pretrained(model_id, device_map="cuda")
    quantiles, mean = pipeline.predict_quantiles(
        context,
        prediction_length=prediction_length,
        quantile_levels=[0.1, 0.5, 0.9],
    )
    return {
        "status": "passed",
        "model_id": model_id,
        "device": torch.cuda.get_device_name(0),
        "runtime_seconds": round(time.perf_counter() - started, 4),
        "quantile_shape": list(quantiles.shape),
        "mean_shape": list(mean.shape),
        "torch_version": torch.__version__,
    }


def format_result(result: dict[str, Any]) -> str:
    return json.dumps(result, indent=2, default=str)
