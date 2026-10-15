"""Repeated same-case comparison of verification ablations and judge sizes.

No verification is modeled as pass-through (no review flag). Labels are the
case author's expected labels, not independent clinical adjudication.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import settings
from app.models import Claim, Fact, Sentence, State
from app.pipeline.entailment import check_claim_entailment
from app.pipeline import verify as verify_module
from app.pipeline.verify import verify_claims

CASES = ROOT / "eval/heldout/cases.json"
OUT = ROOT / "eval/heldout/verification_ablation.json"
FLAG_REASONS = {
    "unsupported_addition": {"unsupported_numeric_detail", "unsupported_attribution", "unsupported_medication_name", "instruction_polarity_mismatch", "unsupported_claim_detail", "unsupported_medication_context"},
    "missing_detail": {"unsupported_claim_detail", "medication_dose_mismatch", "medication_frequency_mismatch", "medication_duration_mismatch", "medication_timing_mismatch"},
    "medication_change": {"medication_dose_mismatch", "medication_frequency_mismatch", "medication_duration_mismatch", "medication_timing_mismatch", "instruction_polarity_mismatch"},
    "wrong_source_link": {"invalid_or_missing_source", "invalid_or_missing_fact"},
}


def build(row):
    sentences = [Sentence(**x) for x in row["sentences"]]
    kind = {"S1": "diagnosis", "S2": "medication", "S3": "appointment", "S4": "warning_sign"}
    facts = [Fact(id=f"F-{row['case_id']}-{s.id}", kind=kind[s.id], text_en=s.text, attrs={}, source_ids=[s.id]) for s in sentences]
    linked_source = row.get("linked_source_id") or ("S1" if row["challenge_family"] == "paraphrased_claim_change" else "S2")
    claim = Claim(id=f"C-{row['case_id']}", text=row["claim"], language="en", fact_ids=[f"F-{row['case_id']}-{linked_source}"], source_ids=row["claim_source_ids"], state=State.NEEDS_CLINICIAN)
    return claim, sentences, facts


def flags(reasons):
    return sorted(label for label, codes in FLAG_REASONS.items() if set(reasons) & codes)


def binary_outcome(verdict, case_flags):
    """Fail closed: only an explicitly supported claim passes evaluation."""
    return {"verdict": "passed" if verdict == "supported" and not case_flags else "failed", "flags": case_flags}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", nargs="+", default=["qwen3:1.7b", "qwen3:8b"])
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--cases", type=Path, default=CASES)
    parser.add_argument("--output", type=Path, default=OUT)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    corpus = json.loads(args.cases.read_text())
    challenge_count = sum(row["challenge_family"] != "clean_control" for row in corpus["cases"])
    control_count = len(corpus["cases"]) - challenge_count
    report = {
        "scope": f"paired evaluation on {challenge_count} synthetic challenge cases and {control_count} clean controls",
        "case_count": len(corpus["cases"]),
        "challenge_case_count": challenge_count,
        "clean_control_count": control_count,
        "repeats": args.repeats,
        "paired_judge_sampling": True,
        "paired_judge_sampling_note": "The standalone judge result is reused when the production full verifier reaches its entailment layer, so judge-only and full-verifier conditions share the same model verdict per case and repeat.",
        "models": {},
        "limitations": ["Author expected labels are not clinician adjudication.", "No verification is treated as pass-through with no review flags.", "Verdict flip means any change among supported, unsupported, and uncertain across repetitions; deterministic-only flags are stable by design."],
    }
    if args.resume and args.output.exists():
        report = json.loads(args.output.read_text())
    original_model, original_enabled = settings.model_id, settings.entailment_judge_enabled
    try:
        for model in args.models:
            if model not in report["models"]:
                report["models"][model] = {"trials": []}
            model_report = report["models"][model]
            trials = model_report["trials"]
            while len(trials) < args.repeats:
                rep = len(trials)
                partial = model_report.get("partial_trial", {})
                if partial.get("repeat") != rep + 1:
                    partial = {"repeat": rep + 1, "cases": []}
                row_results = partial["cases"]
                settings.model_id = model
                settings.entailment_judge_enabled = True
                for row in corpus["cases"][len(row_results):]:
                    claim, sentences, facts = build(row)
                    linked = [next(f for f in facts if f.id == claim.fact_ids[0]).text_en]
                    judge_status, judge_reasons = check_claim_entailment(claim.text, linked, enabled=True)
                    judge_verdict = {"passed": "supported", "failed": "unsupported", "review_suggested": "uncertain"}.get(judge_status, "error")

                    # Reuse the exact standalone judge result when the production
                    # verifier reaches its entailment layer. This keeps conditions
                    # paired and avoids sampling model variation between ablations.
                    settings.entailment_judge_enabled = True
                    status_by_verdict = {"supported": "passed", "unsupported": "failed", "uncertain": "review_suggested", "error": "not_run"}
                    original_check = verify_module.check_claim_entailment
                    verify_module.check_claim_entailment = lambda text, source_facts, *, enabled: (
                        status_by_verdict[judge_verdict],
                        ["unsupported_claim_detail"] if judge_verdict == "unsupported" else (["uncertain_claim_entailment"] if judge_verdict == "uncertain" else (["entailment_judge_failed"] if judge_verdict == "error" else [])),
                    ) if enabled and text == claim.text and source_facts == linked else original_check(text, source_facts, enabled=enabled)
                    full_claim, full_sentences, full_facts = build(row)
                    try:
                        verify_claims([full_claim], full_sentences, full_facts)
                    finally:
                        verify_module.check_claim_entailment = original_check
                    # Deterministic reasons are obtained with the judge disabled so the
                    # three layers can be compared independently.
                    settings.entailment_judge_enabled = False
                    det_claim, det_sentences, det_facts = build(row)
                    verify_claims([det_claim], det_sentences, det_facts)
                    det_flags = flags(det_claim.reason_codes)
                    full_flags = flags(full_claim.reason_codes)
                    full_status = full_claim.checks.get("entailment_judge", "not_run")
                    full_verdict = "unsupported" if any(status == "failed" for name, status in full_claim.checks.items() if name != "entailment_judge") else ("uncertain" if full_status in {"review_suggested", "not_run", "not_configured"} else "supported")
                    row_results.append({
                        "case_id": row["case_id"], "expected_labels": row["author_expected_labels"],
                        "expected_result": "failed" if row["author_expected_labels"] else "passed",
                        "challenge_family": row["challenge_family"],
                        "no_verification": binary_outcome("supported", []),
                        "judge_only": binary_outcome(judge_verdict, ["judge_unsupported"] if judge_verdict == "unsupported" else []),
                        "deterministic_only": binary_outcome("unsupported" if det_flags else "supported", det_flags),
                        "full_verifier": binary_outcome(full_verdict, full_flags),
                    })
                    model_report["partial_trial"] = {"repeat": rep + 1, "cases": row_results}
                    args.output.parent.mkdir(parents=True, exist_ok=True)
                    args.output.write_text(json.dumps(report, indent=2) + "\n")
                settings.entailment_judge_enabled = original_enabled
                trials.append({"repeat": rep + 1, "cases": row_results})
                model_report["updated_unix"] = int(time.time())
                model_report.pop("partial_trial", None)
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(report, indent=2) + "\n")
                print(f"{model}: completed repeat {rep + 1}/{args.repeats}", flush=True)
    finally:
        settings.model_id, settings.entailment_judge_enabled = original_model, original_enabled
    return report


if __name__ == "__main__":
    main()
