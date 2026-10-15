# Reproducible local demo

This walk-through uses synthetic summaries only. It does not use AMD ROCm/vLLM; the current demo model is Ollama on the configured local machine.

## Start the services

1. Install the Python requirements and frontend packages using the commands in [README.md](README.md#quick-start).
2. Start Ollama locally and confirm the configured model is already installed with `ollama list`. The default is `qwen3:1.7b`; the application does not download models.
3. Copy `.env.example` to `.env` in the repository root. For Docker Compose, set `LLM_BASE_URL=http://host.docker.internal:11434/v1`. For the native backend quick start, use `http://localhost:11434/v1`.
4. Start the backend and frontend, or use `docker compose up --build` after configuring `.env`.
5. Open `http://localhost:3000`, select one of the built-in synthetic summaries, choose English or Hindi, and submit it.

Only a local/private model endpoint is accepted by the backend. Keep both demo services bound to localhost and do not enter real patient information.

## Walk through the evidence

1. Select a claim to highlight its source sentence.
2. Expand **Verification checks** to inspect the source wording, generated explanation, rule result, and any reason for review.
3. Note that translated claims require bilingual review, and that all claims remain review suggestions or clinician-review items. The prototype does not mark claims clinically verified.
4. Open **Reviewer queue** and record an approve, edit, or reject workflow action. An approval is not clinical verification.
5. Delete the demo document when finished.

## Reproduce evaluation artifacts

Run from the repository root after installing backend requirements:

```bash
backend/.venv/bin/python eval/run_eval.py
backend/.venv/bin/python eval/evaluate_translation.py
```

`eval/run_eval.py` writes the extraction, source-link, trap, and corruption report to `eval/results/latest.json`. It includes a SHA-256 fingerprint of the synthetic source and gold files and reports extraction metrics separately for generated templates and curated narrative examples.

`eval/evaluate_translation.py` calls the configured local model for six fixed Hindi synthetic cases. It writes generated outputs and token checks to `eval/results/translation_audit.json`, plus a blank or previously completed rating sheet at `eval/results/translation_adjudication.csv`. A qualified Hindi reviewer should rate each case. Use 1–5 for semantic fidelity, readability, and naturalness; yes/no for preservation of critical details, omissions, and additions; include reviewer qualification and review date. Re-running the script retains ratings for the same model and case IDs. Semantic quality is only reported for complete rows with valid fields; no rating is inferred from protected-token checks.

In the latest recorded audit, the configured local endpoint did not complete any of the 12 translations. The report records 12 failures, a null token-preservation rate (there were no translated outputs to score), and zero human ratings. Start the local model service and rerun the audit before collecting bilingual ratings.

The recorded benchmark files under `bench/results/` are from x86_64 Ollama runs, not AMD hardware. The ROCm/vLLM path in `amd/` is a serving template and is not part of this reproducible demo.
