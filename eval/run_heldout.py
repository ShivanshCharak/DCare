"""Run the pinned local judge and deterministic verifier on held-out cases."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.config import settings
from app.models import Claim, Fact, Sentence, State
from app.pipeline.verify import verify_claims

CASE_PATH = ROOT / "eval/heldout/cases.json"
OUTPUT_PATH = ROOT / "eval/heldout/system_predictions.json"
PINNED_MODEL = "qwen3:1.7b"
PINNED_DIGEST = "8f68893c685c3ddff2aa3fffce2aa60a30bb2da65ca488b61fff134a4d1730e7"
FLAG_REASONS = {
    "unsupported_addition": {"unsupported_numeric_detail", "unsupported_attribution", "unsupported_medication_name", "instruction_polarity_mismatch"},
    "missing_detail": {"unsupported_claim_detail", "medication_dose_mismatch", "medication_frequency_mismatch", "medication_duration_mismatch"},
    "medication_change": {"medication_dose_mismatch", "medication_frequency_mismatch", "medication_duration_mismatch", "instruction_polarity_mismatch"},
    "wrong_source_link": {"invalid_or_missing_source", "invalid_or_missing_fact"},
}


def check_model_endpoint() -> None:
    if settings.model_id != PINNED_MODEL:
        raise RuntimeError(f"Expected pinned model {PINNED_MODEL}; configured {settings.model_id}.")
    base = settings.llm_base_url.rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    parsed = urlparse(base)
    url = f"{base}/api/tags"
    try:
        response = httpx.get(url, timeout=3.0)
        response.raise_for_status()
        tags = response.json().get("models", [])
    except Exception as exc:
        raise RuntimeError(f"Ollama health check failed at {url}; no results were written.") from exc
    models = {model.get("name"): model for model in tags}
    if PINNED_MODEL not in models:
        raise RuntimeError(f"Pinned model {PINNED_MODEL} is not installed at {parsed.netloc}; no results were written.")
    if models[PINNED_MODEL].get("digest") != PINNED_DIGEST:
        raise RuntimeError(f"Installed {PINNED_MODEL} digest does not match the pinned version; no results were written.")


def run() -> dict:
    check_model_endpoint()
    corpus = json.loads(CASE_PATH.read_text(encoding="utf-8"))
    output_cases = []
    for row in corpus["cases"]:
        sentences = [Sentence(**item) for item in row["sentences"]]
        kind_by_source = {"S1": "diagnosis", "S2": "medication", "S3": "appointment", "S4": "warning_sign"}
        facts = [Fact(id=f"F-{row['case_id']}-{sentence.id}", kind=kind_by_source[sentence.id], text_en=sentence.text, attrs={}, source_ids=[sentence.id]) for sentence in sentences]
        linked_source_id = "S1" if row["challenge_family"] == "paraphrased_claim_change" else "S2"
        linked_fact_id = f"F-{row['case_id']}-{linked_source_id}"
        claim = Claim(id=f"C-{row['case_id']}", text=row["claim"], language="en", fact_ids=[linked_fact_id], source_ids=row["claim_source_ids"], state=State.NEEDS_CLINICIAN)
        verify_claims([claim], sentences, facts)
        status = claim.checks.get("entailment_judge")
        expected_skip = row["challenge_family"] == "wrong_source_link"
        if settings.entailment_judge_enabled and not expected_skip and status not in {"passed", "failed", "review_suggested"}:
            raise RuntimeError(f"The entailment judge did not complete for {row['case_id']}; no results were written.")
        judge = {"passed": "supported", "failed": "unsupported", "review_suggested": "uncertain"}.get(status, "not_run")
        output_cases.append({
            "case_id": row["case_id"],
            "deterministic_flags": sorted(name for name, reasons in FLAG_REASONS.items() if set(claim.reason_codes) & reasons),
            "deterministic_reasons": claim.reason_codes,
            "entailment_judge": judge,
        })
    report = {
        "scope": "held-out synthetic discharge-summary claim audit",
        "model_id": PINNED_MODEL,
        "model_digest": PINNED_DIGEST,
        "case_count": len(output_cases),
        "cases": output_cases,
        "human_adjudication": "pending; see reviewer_labels.csv",
        "limitations": ["System flags are preliminary outputs, not human labels.", "Do not report misses, false alarms, or judge agreement as human-validated until the worksheet is completed by a qualified reviewer."],
    }
    OUTPUT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    result = run()
    print(f"Saved {result['case_count']} held-out predictions with {result['model_id']} to {OUTPUT_PATH}")
