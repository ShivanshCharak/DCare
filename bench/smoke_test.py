"""Synthetic model smoke test for a local Ollama endpoint."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv
import httpx

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def configured(value: str) -> bool:
    return bool(value and "replace" not in value.casefold())


def run_smoke_test(base_url: str, api_key: str, model: str) -> dict:
    del api_key  # Local Ollama does not require API-key authentication.
    endpoint = base_url.rstrip("/")
    if endpoint.endswith("/v1"):
        endpoint = endpoint[:-3]
    tags = httpx.get(f"{endpoint}/api/tags", timeout=15.0)
    tags.raise_for_status()
    model_ids = [item.get("name") for item in tags.json().get("models", [])]
    if model not in model_ids:
        raise ValueError("Configured model ID was not returned by the endpoint")

    response = httpx.post(
        f"{endpoint}/api/chat",
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": "Return exactly the word OK."},
                {"role": "user", "content": "Synthetic endpoint smoke test."},
            ],
            "think": False,
            "stream": False,
            "options": {"temperature": 0, "num_predict": 8},
        },
        timeout=30.0,
    )
    response.raise_for_status()
    if not response.json().get("message", {}).get("content", "").strip():
        raise ValueError("Endpoint returned an empty completion")
    return {
        "model_list_request_succeeded": True,
        "configured_model_listed": True,
        "completion_request_succeeded": True,
        "endpoint_host": urlsplit(base_url).hostname,
        "model_id": model,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Validate configuration without contacting the endpoint")
    args = parser.parse_args()
    base_url = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")
    model = os.getenv("MODEL_ID", "qwen3:1.7b")

    if args.dry_run:
        print(json.dumps({
            "endpoint_host": urlsplit(base_url).hostname,
            "model_id_configured": configured(model),
            "contacts_endpoint": False,
        }, indent=2))
        return

    if not configured(model):
        parser.error("Set MODEL_ID to an installed model served by the endpoint")
    try:
        result = run_smoke_test(base_url, "", model)
    except Exception as exc:
        # Avoid printing request details that could contain endpoint or credential data.
        parser.exit(1, f"Smoke test failed ({type(exc).__name__}). Check endpoint/model configuration.\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
