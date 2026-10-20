"""Smoke-test the synthetic demo artifact through the FastAPI analysis route."""

from __future__ import annotations

import argparse

from fastapi.testclient import TestClient

import api.main as api
from src.predict import load_model


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, help="Path to a demo candidate model artifact")
    args = parser.parse_args()

    bundle = load_model(args.model)
    original_get_model = api.get_model
    original_model = api._model
    try:
        api._model = bundle
        api.get_model = lambda: bundle
        response = TestClient(api.app).post("/analyze", json={"message": "Claim your fictional demo prize now!"})
        if response.status_code != 200:
            raise RuntimeError(f"Synthetic demo API smoke test failed with status {response.status_code}.")
        body = response.json()
        if body.get("model_version") != bundle.version or body.get("prediction") not in {"ham", "spam"}:
            raise RuntimeError("Synthetic demo API response did not match the loaded candidate artifact.")
    finally:
        api.get_model = original_get_model
        api._model = original_model

    print(
        {
            "api_smoke": "passed",
            "model_version": bundle.version,
            "synthetic_training_data": bundle.metadata.get("synthetic_training_data"),
            "feature_mode": bundle.metadata.get("text_feature_mode"),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
