# DCare / Discharge Explainer

Prototype that turns hospital discharge notes into plain-language explanations (English and Hindi), links each claim to its source, and uses deterministic checks plus a local LLM-as-a-judge to route uncertain claims for human review.

Built for the [AMD Developer Hackathon: Act III](https://lablab.ai/ai-hackathons/amd-developer-hackathon-act-iii).

## How it works

1. Split a discharge note into numbered source sentences and extract structured facts.
2. Generate a plain-language explanation for each fact with a local Ollama model.
3. Optionally translate explanations into Hindi with a second model review pass.
4. Check source links, numbers, dates, medication details, negation, and conflicting instructions. A local LLM-as-a-judge compares each explanation claim with its linked source facts and flags unsupported or uncertain claims.
5. Send uncertain or flagged claims to a human review queue. Claims are never marked clinically verified.

The backend accepts local or private-network model endpoints and rejects public endpoints. The default model is `qwen3:1.7b`. 

## Evaluation results

### Extraction and rule checks

Fresh run on 2026-10-15 using the synthetic corpus and hand-authored mutations:

| Evaluation | Result |
| --- | ---: |
| Exact fact extraction | 340/340 facts; precision 1.00, recall 1.00, F1 1.00 |
| Source links | 340/340 exact matches |
| Cross-fact conflict traps detected | 14/14 |
| Clean documents falsely flagged for cross-fact conflict | 0/45 |
| Hand-authored claim mutations detected | 12/12 |
| Clean control claims falsely flagged for mutation | 0/11 |

### Verification comparison

Across five repeated runs, the verifier was evaluated on 40 challenge examples containing unsupported changes and 40 clean examples copied from their cited sources. Each row shows the outcome per run; results were consistent across all five runs.

| Verification setup | Model | Challenge examples flagged | Challenge examples not flagged | Clean examples flagged |
| --- | --- | ---: | ---: | ---: |
| No verification | — | 0/40 | 40/40 | 0/40 |
| Deterministic checks only | — | 35/40 | 5/40 | 0/40 |
| LLM judge only | Qwen 1.7B | 27/40 | 13/40 | 2/40 |
| Full verifier | Qwen 1.7B | 38/40 | 2/40 | 0/40 |
| LLM judge only | Qwen 8B | 25/40 | 15/40 | 0/40 |
| Full verifier | Qwen 8B | 38/40 | 2/40 | 0/40 |

In this comparison, the full verifier flagged 38 of 40 challenge examples and none of the 40 source-matched controls. These results are from author-labeled examples; the clean controls use exact source copies, and the evaluation has not been independently or clinically adjudicated. They are useful for tracking changes to these checks, not as a measure of clinical accuracy.

### Result files and reproduction

- [Raw five-repeat verification results](eval/heldout/verification_ablation_controls.json)
- [Verification result summary](eval/heldout/verification_ablation_summary.md)
- [Challenge and control cases](eval/heldout/ablation_cases.json)
- [Verification comparison runner](eval/run_verification_ablation.py)
- [Latest extraction and mutation report](eval/results/latest.json)
- [Generated mutation cases](eval/results/corruptions.json)

Re-run the deterministic corpus and mutation evaluations from the repository root:

```bash
backend/.venv/bin/python eval/corrupt.py
backend/.venv/bin/python eval/run_eval.py
```

The Qwen comparison requires Ollama with the requested models already installed. The saved results record five completed repeats for both models; the Ollama service was unavailable during this README update, so that model comparison was not rerun here.

## Run locally

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend

In another terminal:

```bash
cd frontend
cp .env.example .env.local
npm install
npm run dev
```

Open <http://localhost:3000>. The frontend expects the backend at `http://localhost:8000` by default. For a repeatable synthetic-only demo, see [DEMO.md](DEMO.md).

### Local model configuration

Start Ollama and install the model tags you want to use. The defaults are `MODEL_ID=qwen3:1.7b`, `TRANSLATION_MODEL_ID=qwen3:1.7b`, and `TRANSLATION_JUDGE_MODEL_ID=qwen3:1.7b`. Copy `.env.example` to `.env` to configure the backend. Do not commit `.env`, credentials, or patient documents.


## API

- `GET /health`
- `GET /health/model` (reports configuration, not endpoint availability)
- `POST /documents` — JSON text or PDF upload
- `POST /documents/{doc_id}/explain?lang=en|hi`
- `GET /documents/{doc_id}`
- `DELETE /documents/{doc_id}`
- `GET /review-queue`
- `POST /claims/{claim_id}/review`
- `GET /doctor-questions/{doc_id}`
