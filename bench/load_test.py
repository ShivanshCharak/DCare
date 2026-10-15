"""Measure a local Ollama model using synthetic prompts."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import platform
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
DEFAULT_OUTPUT = ROOT / "bench" / "results" / "latest.json"
SYNTHETIC_PROMPT = (
    "Rewrite this synthetic discharge-summary fact in simple English without "
    "adding information: Attend the follow-up appointment in 7 days."
)


def ollama_version() -> str | None:
    executable = shutil.which("ollama")
    if executable is None:
        return None
    try:
        result = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            timeout=3.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() or result.stderr.strip() or None


def ollama_model_processor(model: str) -> str | None:
    executable = shutil.which("ollama")
    if executable is None:
        return None
    try:
        result = subprocess.run(
            [executable, "ps"],
            capture_output=True,
            text=True,
            timeout=3.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    for line in result.stdout.splitlines()[1:]:
        fields = line.split()
        if fields and fields[0] == model:
            match = re.search(r"\b\d+%\s+(?:GPU|CPU)\b", line)
            return match.group(0) if match else None
    return None


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(fraction * len(ordered)) - 1)
    return ordered[index]


async def request_completion(
    client: httpx.AsyncClient,
    endpoint: str,
    model: str,
    api_key: str,
) -> dict:
    del api_key  # Local Ollama does not require API-key authentication.
    start = time.perf_counter()
    first_token_at: float | None = None
    completion_tokens: int | None = None
    content_parts: list[str] = []
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Restate only the supplied synthetic fact."},
            {"role": "user", "content": SYNTHETIC_PROMPT},
        ],
        "stream": True,
        "think": False,
        "options": {"temperature": 0},
    }

    async with client.stream(
        "POST",
        endpoint,
        json=payload,
    ) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if not line:
                continue
            chunk = json.loads(line)
            content = (chunk.get("message") or {}).get("content")
            if isinstance(content, str) and content:
                if first_token_at is None:
                    first_token_at = time.perf_counter()
                content_parts.append(content)
            if isinstance(chunk.get("eval_count"), int):
                completion_tokens = chunk["eval_count"]
            if chunk.get("done"):
                break

    finished = time.perf_counter()
    return {
        "latency_seconds": finished - start,
        "ttft_seconds": first_token_at - start if first_token_at is not None else None,
        "completion_tokens": completion_tokens,
        "output_chars": sum(map(len, content_parts)),
    }


async def run_level(
    client: httpx.AsyncClient,
    endpoint: str,
    model: str,
    api_key: str,
    concurrency: int,
    request_count: int,
) -> dict:
    semaphore = asyncio.Semaphore(concurrency)

    async def bounded_request() -> dict:
        async with semaphore:
            return await request_completion(client, endpoint, model, api_key)

    start = time.perf_counter()
    results = await asyncio.gather(*(bounded_request() for _ in range(request_count)))
    elapsed = time.perf_counter() - start
    latencies = [item["latency_seconds"] for item in results]
    ttfts = [item["ttft_seconds"] for item in results if item["ttft_seconds"] is not None]
    known_tokens = [
        item["completion_tokens"]
        for item in results
        if isinstance(item["completion_tokens"], int)
    ]
    total_tokens = sum(known_tokens)

    return {
        "concurrency": concurrency,
        "request_count": request_count,
        "elapsed_seconds": elapsed,
        "ttft_p50_seconds": percentile(ttfts, 0.50),
        "ttft_p95_seconds": percentile(ttfts, 0.95),
        "latency_p50_seconds": percentile(latencies, 0.50),
        "latency_p95_seconds": percentile(latencies, 0.95),
        "completion_tokens_reported": total_tokens if len(known_tokens) == len(results) else None,
        "completion_tokens_available_for_requests": len(known_tokens),
        "aggregate_tokens_per_second": total_tokens / elapsed if len(known_tokens) == len(results) and elapsed else None,
        "documents_per_minute": request_count * 60 / elapsed if elapsed else None,
    }


async def run_benchmark(
    base_url: str,
    api_key: str,
    model: str,
    concurrency_levels: list[int],
    request_count: int,
) -> dict:
    endpoint = base_url.rstrip("/")
    if endpoint.endswith("/v1"):
        endpoint = endpoint[:-3]
    endpoint += "/api/chat"
    timeout = httpx.Timeout(connect=15.0, read=300.0, write=30.0, pool=30.0)
    limits = httpx.Limits(max_connections=max(concurrency_levels), max_keepalive_connections=max(concurrency_levels))
    async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
        levels = []
        for concurrency in concurrency_levels:
            levels.append(
                await run_level(client, endpoint, model, api_key, concurrency, request_count)
            )

    return {
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "synthetic_prompts_only": True,
        "endpoint_host": urlsplit(base_url).hostname,
        "model_id": model,
        "host_metadata": {
            "architecture": platform.machine(),
            "logical_cpu_count": os.cpu_count(),
            "ollama_version": ollama_version(),
        },
        "model_processor": ollama_model_processor(model),
        "gpu_name": os.getenv("OLLAMA_GPU_NAME") or os.getenv("AMD_GPU_NAME"),
        "requests_per_concurrency_level": request_count,
        "results": levels,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--concurrency", nargs="+", type=int, default=[1, 8, 32])
    parser.add_argument("--requests-per-level", type=int, default=32)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--dry-run", action="store_true", help="Show run settings without contacting an endpoint")
    args = parser.parse_args()

    if not args.concurrency or any(value < 1 for value in args.concurrency):
        parser.error("concurrency values must be positive integers")
    if args.requests_per_level < 1:
        parser.error("--requests-per-level must be positive")

    base_url = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")
    model = os.getenv("MODEL_ID", "qwen3:1.7b")
    api_key = ""

    if args.dry_run:
        print(
            json.dumps(
                {
                    "endpoint_host": urlsplit(base_url).hostname,
                    "model_id_configured": bool(model and "replace" not in model.casefold()),
                    "concurrency": args.concurrency,
                    "requests_per_level": args.requests_per_level,
                    "contacts_endpoint": False,
                },
                indent=2,
            )
        )
        return

    if not model or "replace" in model.casefold():
        parser.error("Set MODEL_ID to an installed model served by the endpoint")
    report = asyncio.run(
        run_benchmark(base_url, api_key, model, args.concurrency, args.requests_per_level)
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"Saved benchmark results to {args.output}")


if __name__ == "__main__":
    main()
