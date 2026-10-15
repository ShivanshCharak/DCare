# Discharge Explainer

A safety-first prototype that turns a **synthetic** hospital discharge summary into a plain-language explanation. Each claim retains source sentence IDs and is routed to `review_suggested` or `needs_clinician`; the prototype does not mark claims clinically verified.

> **Safety:** This prototype is not medical advice. It does not diagnose, prescribe, or add medical instructions. Use synthetic documents only. Nothing in this scaffold is clinically validated.

## Architecture

- `frontend/`: Next.js + TypeScript + Tailwind UI scaffold
- `backend/`: FastAPI API and pipeline modules
- `data/`: synthetic examples, gold labels, glossary and risk rules
- `eval/`: synthetic corruption/evaluation harness and recorded smoke-run results
- `bench/`: synthetic local model smoke test and benchmark
- `amd/`: AMD ROCm/vLLM deployment notes and script template (not yet integrated)
- `DEMO.md`: reproducible synthetic-only local demo

```mermaid
flowchart LR
  A[Synthetic text or PDF] --> B[Local parsing and sentence IDs]
  B --> C[Deterministic fact extraction]
  C --> D[Local Ollama explanation]
  D --> E[Source and detail checks]
  E --> F[Human review queue: all claims]
  E -. enabled in .env.example; requires a working local model .-> I[Local entailment judge]
  I -. can add review flags .-> F
  F --> G[Ordered by review priority score]
  G --> J[SQLite demo store]
```

## Quick start

### 1. Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Health check: <http://localhost:8000/health>

### 2. Frontend

In a second terminal:

```bash
cd frontend
cp .env.example .env.local
npm install
npm run dev
```

Open <http://localhost:3000>. Set `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000`.

### 3. Environment

Copy the root `.env.example` to `.env` for backend configuration. Do not commit `.env`, API keys, patient documents, or credentials.

The backend enforces a 5 MB request-body limit by default; adjust `MAX_REQUEST_BYTES` only for a controlled local demo. `LLM_BASE_URL` is backend-only, and the client rejects endpoints outside localhost or a private network to prevent sending source text to a public model API. The entailment judge is enabled by default and uses the configured local model; if the model is unavailable, the check reports that it did not run. Hindi translations also run a local English back-translation and compare its details with the original English claim. This round trip is only a screening signal, so every translation still requires qualified human review and claims remain unverified. To enable the shared bearer-token gate, set `API_ACCESS_TOKEN` in `.env`; the frontend token field sends it from tab-scoped session storage. In production mode (`APP_ENV=production`), the backend rejects API requests if no token is configured. `/health` stays public for container health checks. This shared token is a basic access gate, not individual user authentication.

Docker Compose publishes the frontend and backend ports on `127.0.0.1` for local-only access. This binding is for the synthetic demo; it is not a production deployment configuration.

### 4. Local Ollama model

The default configuration uses `LLM_BASE_URL=http://localhost:11434/v1` and `MODEL_ID=qwen3:1.7b`. That model is already installed in the development environment, so setup does not need to download a model. The app calls Ollama's native chat API with thinking disabled; the OpenAI-compatible route returned empty user-facing content for Qwen 3. A synthetic appointment rewrite through the native endpoint preserved the source text. This is a smoke check, not a clinical quality evaluation.

For Docker Compose on Linux, the backend connects to Ollama on the host using `host.docker.internal`; keep Ollama running on port 11434. Local development outside Compose uses `localhost`. `amd/serve_vllm.sh` remains a template for a future AMD-hosted endpoint.

`FACT_EXTRACTION_MODE` defaults to `deterministic`; set it to `structured_llm` to use Ollama's native JSON Schema response format. Explanation generation uses the same configured local model.

Hindi translation uses `TRANSLATION_MODEL_ID` (default `qwen3:1.7b`) and a second-pass translation reviewer uses `TRANSLATION_JUDGE_MODEL_ID` (default `qwen3:1.7b`). Both model tags must already be installed in Ollama. The judge can suggest a complete corrected translation and the app checks that protected names and numeric details remain present; every translated claim still requires bilingual human review. Set either variable to another installed local model if needed.

## Current implementation status

- **Input and parsing:** the frontend accepts pasted text and synthetic `.txt` or PDF uploads up to the configured 5 MB request cap, and offers four canned synthetic samples including one with alternate section headings. `pysbd` splits text into numbered source sentences and recognizes a small set of section headings. Scanned pages use local Tesseract OCR (English and Hindi language data when installed), with a 25-page default limit. OCR-derived claims are always routed for clinician review; OCR recognition still needs comparison with the scanned page.
- **Fact extraction:** deterministic section-based extraction is the default. Optional `FACT_EXTRACTION_MODE=structured_llm` asks local Ollama to return only fact kinds and source sentence IDs under a JSON Schema; fact text is copied from the source sentence. Invalid output falls back to deterministic extraction, and structured-mode claims carry a human-review reason. The native Ollama structured-response path has not been verified live.
- **Explanations:** one English claim is generated per fact through Ollama's native local chat API with thinking disabled. If generation fails, the source fact is retained and the claim is routed to clinician review. Claims are never automatically marked verified; the synthetic smoke check does not validate broader output quality.
- **Translation:** Hindi uses the configured translation model, then a second model pass checks for meaning changes, omissions, additions, and clarity and can suggest a correction. Deterministic checks still enforce protected names and numeric details. Every translation remains in human review until checked by a qualified bilingual reviewer; neither the AI judge nor back-translation establishes accuracy, safety, or readability. The saved six-case audit uses Qwen 1.7B and found 2/6 outputs preserved all protected details; no human semantic ratings are recorded. Use `eval/translation_review.html` to rate exact source/output pairs and export decisions and corrected translations. A translation failure keeps the English claim and labels its language as English.
- **Verification and routing:** source/fact links, exact text equality, numeric values and dates, medication dose/frequency/duration consistency, supported generic medication names, ambiguous medication instructions, negation, stop/continue changes, cross-fact medication conflicts, unsupported attribution, and configured high-alert medication mentions are checked. Claims that exactly match their cited source, or match a small set of recognized wording equivalents such as “daily” and “once a day,” are marked **source supported** and removed from the review queue when no other check raises an issue. This status confirms source fidelity only; it does not establish that the source instruction is medically correct. Failed or uncertain checks remain in the review queue, and the displayed **review priority score** only orders that queue; it is not a probability of correctness. The local LLM entailment judge can add review flags but cannot clear deterministic failures or mark claims clinically verified. Translation claims remain in human review because an AI judge and English back-translation are screening signals; translation meaning still needs qualified bilingual assessment. Name and contradiction coverage is incomplete; none of these checks establish clinical correctness.
- **Routing and review:** claims with invalid sources, medication mismatches, generation failures, unsupported attribution, or enabled entailment-judge concerns go to clinician review. Other claims remain review-suggested. High-alert medication mentions carry an explicit review reason. The review API and UI record approve/edit/reject actions; approval does not set a claim to clinically verified.
- **Questions and storage:** a basic doctor-question list is generated. Documents and review decisions persist in SQLite (`DATABASE_URL`); Docker Compose mounts a named volume. Documents expire after `DOCUMENT_RETENTION_DAYS` (7 by default; `0` disables expiry), and `DELETE /documents/{doc_id}` removes a row immediately with SQLite `secure_delete` enabled. API access uses the existing shared bearer-token gate; this is not individual authentication. SQLite encryption-at-rest, per-user authorization, and multi-user deployment guarantees are not implemented. Use synthetic data only.
- **Frontend:** the explainer supports pasted summaries and `.txt`/PDF uploads, English/Hindi selection, source-linked claims, evidence checks, doctor questions, review priority scores, and inline review actions. `/review-queue` lists pending claims ordered by review priority with linked source sentences and records approve/edit/reject actions; edited claims remain unverified pending re-verification. A document can be explicitly deleted from the explainer.
- **Evaluation and model benchmark:** `eval/run_eval.py` is the regression evaluation for the templated and curated synthetic corpus; it reports extraction precision/recall/F1 and source-link accuracy overall and by authoring style, plus a SHA-256 data manifest. Existing results in `eval/results/latest.json` cover 59 documents and 340 labeled facts; the cross-fact conflict detector caught 14/14 synthetic traps with 0/45 clean-document flags, and the verifier caught 12/12 hand-authored mutations with 0/11 clean-control flags. A separate 40-summary varied synthetic held-out review set is prepared in `eval/heldout/`; its clinician/student adjudication is pending, so it has no human miss, false-alarm, or 1.7B judge-agreement results yet. These synthetic materials do not establish clinical performance. `eval/evaluate_translation.py` runs six independently authored synthetic cases with the pinned `qwen3:1.7b` digest, creates `eval/results/translation_adjudication.csv` for qualified bilingual review, and reports 6/6 translations completed, 2/6 protected-token passes, and 0 completed human reviews in `eval/results/translation_audit.json`. Translation meaning quality remains unmeasured. The saved Ollama benchmark ran on x86_64, not AMD ROCm. `/health/model` reports configuration only, not endpoint availability.
- **Verification status:** fresh runs passed 117 backend tests and 8 frontend tests, with no failures. GitHub Actions runs both suites on pushes and pull requests. The translation audit reports 6/6 translations completed, 2/6 protected-token passes, and no completed bilingual human ratings.

These are prototype signals, not clinical-grade checks. The high-alert names are a partial generic-name subset adapted from the [ISMP acute-care high-alert medication list (January 2024)](https://www.ismp.org/system/files/resources/2024-01/ISMP_HighAlert_AcuteCare_List_010924_MS5760.pdf). The rules do not enforce all route/formulation qualifiers and can therefore over-flag; they are only a prompt for human review, not a clinical reference. The corpus and medication aliases remain small starter data and must be expanded and validated before any real-world use.

## Safety principles

1. Only synthetic data in development and demos.
2. Every claim must preserve source sentence IDs.
3. Any unsupported number, medication name, date, contradiction, or uncertain model result must not be silently shown as verified.
4. High-alert medication rules should default to human review.
5. A reviewer decision is not a substitute for clinical validation.
6. Report actual evaluation results and limitations; do not invent performance numbers.

## API overview

- `GET /health`
- `GET /health/model` (configuration only; `/health/amd` remains as a hidden compatibility alias)
- `POST /documents` — JSON `{ "text": "..." }` or multipart PDF upload
- `POST /documents/{doc_id}/explain?lang=en|hi`
- `GET /documents/{doc_id}`
- `DELETE /documents/{doc_id}`
- `GET /review-queue`
- `POST /claims/{claim_id}/review`
- `GET /doctor-questions/{doc_id}`

See [DEMO.md](DEMO.md) for a repeatable local run and [eval/README.md](eval/README.md) for metric definitions and bilingual adjudication steps.

The SQLite store is intended for this local, synthetic-data demo. A configurable retention period and document deletion endpoint are available, but SQLite encryption at rest and individual user accounts are not implemented. Do not use real patient data or expose this prototype publicly without security review.
