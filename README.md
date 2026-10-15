# DCare / Discharge Explainer

Prototype that turns hospital discharge notes into plain-language explanations in English and 10 Indian languages, links each claim to its source, and uses deterministic checks plus a local LLM-as-a-judge to route uncertain claims for human review.

Built for the [AMD Developer Hackathon: Act III](https://lablab.ai/ai-hackathons/amd-developer-hackathon-act-iii).

## How it works

1. Split a discharge note into numbered source sentences and extract structured facts.
2. Generate a plain-language explanation for each fact with a local Ollama model.
3. Optionally translate explanations into Hindi, Bengali, Gujarati, Kannada, Malayalam, Marathi, Odia, Punjabi, Tamil, or Telugu. Every translation, revision, and back-translation is produced by Sarvam-1; Qwen 1.7B performs the separate second-pass review.
4. Check source links, numbers, dates, medication details, negation, and conflicting instructions. A local LLM-as-a-judge compares each explanation claim with its linked source facts and flags unsupported or uncertain claims.
5. Send uncertain or flagged claims to a human review queue. Claims are never marked clinically verified.

The backend accepts local or private-network model endpoints and rejects public endpoints. The explanation and claim-judge default is `qwen3:1.7b`.

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

### Sarvam multilingual translation benchmark

Run on 2026-10-15 with Sarvam-1 (`mashriram/sarvam-1`, digest `6443034ccda0009f86b5a4570547f1fc7211b58f13bedeb11621ccd267ca45a7`). The fixed project-authored evaluation set contains eight discharge-instruction examples, each translated into the ten Indic languages supported by the app (80 outputs total).

| Language | Outputs completed | Passed strict verbatim token check |
| --- | ---: | ---: |
| Hindi | 8/8 | 4/8 (50%) |
| Bengali | 8/8 | 4/8 (50%) |
| Gujarati | 8/8 | 4/8 (50%) |
| Kannada | 8/8 | 4/8 (50%) |
| Malayalam | 8/8 | 4/8 (50%) |
| Marathi | 8/8 | 4/8 (50%) |
| Odia | 8/8 | 3/8 (37.5%) |
| Punjabi | 8/8 | 4/8 (50%) |
| Tamil | 8/8 | 4/8 (50%) |
| Telugu | 8/8 | 4/8 (50%) |
| **Total** | **80/80** | **39/80 (48.8%)** |

The strict check looks for selected medication names and numbers, doses, units, and dates to remain verbatim in the output. It is not a translation-quality score: equivalent localized numerals or transliterations can fail it. The run had no leftover prompt/example text after translation cleanup. No bilingual human ratings are recorded yet, so semantic accuracy, readability, and clinical safety remain unevaluated. The examples were composed for this project and do not contain patient records; they have not been independently translated or clinically reviewed.

Benchmark artifacts:

- [Sarvam translation report](eval/results/sarvam_multilingual_benchmark.json)
- [Bilingual review worksheet](eval/results/sarvam_multilingual_review.csv)
- [Evaluation instructions](eval/sarvam_translation_cases.json)
- [Benchmark runner](eval/benchmark_sarvam_translation.py)

Re-run with local Ollama and the Sarvam-1 model installed:

```bash
backend/.venv/bin/python eval/benchmark_sarvam_translation.py
```

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

Start Ollama and install the models you want to use. Install Sarvam-1 with `ollama run mashriram/sarvam-1`. The app pins all translation, revision, and back-translation generation to Sarvam-1. `MODEL_ID=qwen3:1.7b` is used for explanation generation and claim judging; `TRANSLATION_JUDGE_MODEL_ID=qwen3:1.7b` is used for second-pass translation review. The available Indic languages follow [Sarvam-1's Ollama model listing](https://ollama.com/mashriram/sarvam-1): Bengali, Gujarati, Hindi, Kannada, Malayalam, Marathi, Odia, Punjabi, Tamil, and Telugu. Sarvam-1 is listed as a text-completion model rather than an instruction-following model. The current evaluation is a small project-authored benchmark with automated token checks; it has no bilingual human ratings and does not establish translation quality or safety. Copy `.env.example` to `.env` to configure the backend. Do not commit `.env`, credentials, or patient documents.


## API

- `GET /health`
- `GET /health/model` (reports configuration, not endpoint availability)
- `POST /documents` — JSON text or PDF upload
- `POST /documents/{doc_id}/explain?lang=en|hi|bn|gu|kn|ml|mr|or|pa|ta|te`
- `GET /documents/{doc_id}`
- `DELETE /documents/{doc_id}`
- `GET /review-queue`
- `POST /claims/{claim_id}/review`
- `GET /doctor-questions/{doc_id}`
