# Local model benchmark

Run the scripts from the repository root after configuring `LLM_BASE_URL` and `MODEL_ID` in `.env` or the shell. Defaults target the already-installed `qwen3:1.7b` model through local Ollama at `http://localhost:11434`. The scripts send only fixed synthetic prompts.

Check the local model endpoint before benchmarking:

```bash
backend/.venv/bin/python bench/smoke_test.py --dry-run
backend/.venv/bin/python bench/smoke_test.py
```

The live smoke test lists installed models and sends one short completion request. It reports success flags, endpoint host, and configured model ID.

```bash
backend/.venv/bin/python bench/load_test.py --dry-run
backend/.venv/bin/python bench/load_test.py --concurrency 1 8 32 --requests-per-level 32
```

The run records time to first streamed text, p50/p95 request latency, documents per minute, model ID, optional `AMD_GPU_NAME`, and output-token throughput when Ollama reports token usage. It writes `bench/results/latest.json`.

The initial 3-request smoke run is saved as `bench/results/ollama-qwen3-1.7b-preliminary.json`. A larger 25-request-per-level run is saved as `bench/results/ollama-qwen3-1.7b-sustained.json`; it records host architecture, logical CPU count, Ollama version, and model processor placement. Ollama reported 100% GPU placement, but the GPU name was unavailable. Both are synthetic-only measurements on one host and are not capacity or clinical-performance guarantees.
