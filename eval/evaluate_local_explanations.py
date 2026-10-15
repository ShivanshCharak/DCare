"""Run a small synthetic generation audit against the configured local model."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import settings
from app.models import Claim, Fact, Sentence
from app.pipeline.extract import extract_facts
from app.pipeline.explain import explain_facts
from app.pipeline.parse import parse_and_split
from app.pipeline.verify import verify_claims

CASES = [
    ("diagnosis", "A synthetic diagnosis of seasonal influenza was recorded at discharge."),
    ("medication", "Take metformin 500 mg twice daily for 5 days."),
    ("medication", "Do not take aspirin until your clinician reviews your medication list."),
    ("appointment", "Attend the follow-up appointment in 7 days."),
    ("appointment", "Your appointment is scheduled for 10/20/2026."),
    ("restriction", "Do not lift objects heavier than 5 kg until your follow-up appointment."),
    ("warning_sign", "Seek urgent help if you have difficulty breathing."),
    ("pending_test", "The final laboratory report is pending."),
    ("medication", "Take acetaminophen 500 mg every 8 hours as needed."),
    ("medication", "Continue taking lisinopril 10 mg once daily until your next review."),
    ("appointment", "Call the clinic if you cannot attend your appointment in 3 days."),
    ("diagnosis", "Your clinician documented a synthetic diagnosis of dehydration."),
]

CHECKS_OF_INTEREST = {
    "source_ids",
    "risk_rules",
    "ambiguous_medication_details",
    "medication_names",
    "unsupported_details",
    "numeric_details",
    "instruction_polarity",
    "medication_contradictions",
}
IGNORED_REASONS = {"verification_layers_not_fully_configured"}
EXPECTED_REVIEW_REASONS = {"high_alert_medication_review"}


def corpus_cases() -> list[tuple[str, str]]:
    """Return each distinct exact fact text in the synthetic corpus once."""
    unique = {
        (fact.kind, fact.text_en)
        for path in (ROOT / "data" / "synthetic").glob("doc_*.txt")
        for fact in extract_facts(parse_and_split(path.read_text(encoding="utf-8")))
    }
    return sorted(unique)


def evaluate(
    *,
    include_corpus: bool = False,
    model_id: str | None = None,
    limit: int | None = None,
) -> dict:
    # This artifact evaluates generation and deterministic signals only.
    # Keep the optional model-as-judge disabled to avoid circular evaluation.
    settings.entailment_judge_enabled = False
    if model_id:
        settings.model_id = model_id
    rows = []
    issue_count = 0
    expected_review_count = 0

    cases = CASES + (corpus_cases() if include_corpus else [])
    if limit is not None:
        cases = cases[:limit]
    for index, (kind, source_text) in enumerate(cases, start=1):
        sentence = Sentence(id=f"S{index}", text=source_text, section=kind)
        fact = Fact(
            id=f"F{index}",
            kind=kind,
            text_en=source_text,
            source_ids=[sentence.id],
        )
        claim = explain_facts([fact])[0]
        verify_claims([claim], [sentence], [fact])
        failed_checks = {
            name: claim.checks.get(name)
            for name in CHECKS_OF_INTEREST
            if claim.checks.get(name) == "failed"
        }
        actionable_reasons = [
            reason
            for reason in claim.reason_codes
            if reason not in IGNORED_REASONS | EXPECTED_REVIEW_REASONS
        ]
        expected_review = bool(EXPECTED_REVIEW_REASONS.intersection(claim.reason_codes))
        issue_count += int(bool(failed_checks or actionable_reasons))
        expected_review_count += int(expected_review)
        rows.append(
            {
                "id": f"synthetic_{index:02d}",
                "kind": kind,
                "source": source_text,
                "generated_claim": claim.text,
                "state": claim.state.value,
                "reason_codes": claim.reason_codes,
                "expected_human_review": expected_review,
                "deterministic_failed_checks": failed_checks,
                "entailment_judge": claim.checks.get("entailment_judge"),
            }
        )

    return {
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "synthetic_only": True,
        "model_id": settings.model_id,
        "includes_distinct_corpus_facts": include_corpus,
        "distinct_corpus_fact_count": len(corpus_cases()) if include_corpus else 0,
        "case_count": len(rows),
        "cases_with_deterministic_flags": issue_count,
        "cases_with_expected_human_review": expected_review_count,
        "scope_note": (
            "Small synthetic generation audit; deterministic checks can miss semantic "
            "errors. This is not a clinical accuracy or safety evaluation."
        ),
        "cases": rows,
    }


def rescore_existing(report_path: Path) -> dict:
    """Rerun current deterministic checks on saved synthetic model outputs."""
    report = json.loads(report_path.read_text(encoding="utf-8"))
    settings.entailment_judge_enabled = False
    issue_count = 0
    expected_review_count = 0
    for row in report["cases"]:
        sentence = Sentence(id="S1", text=row["source"], section=row["kind"])
        fact = Fact(
            id="F1",
            kind=row["kind"],
            text_en=row["source"],
            source_ids=[sentence.id],
        )
        claim = verify_claims(
            [
                Claim(
                    id=row["id"],
                    text=row["generated_claim"],
                    fact_ids=[fact.id],
                    source_ids=[sentence.id],
                )
            ],
            [sentence],
            [fact],
        )[0]
        failed_checks = {
            name: claim.checks.get(name)
            for name in CHECKS_OF_INTEREST
            if claim.checks.get(name) == "failed"
        }
        expected_review = bool(EXPECTED_REVIEW_REASONS.intersection(claim.reason_codes))
        actionable_reasons = [
            reason
            for reason in claim.reason_codes
            if reason not in IGNORED_REASONS | EXPECTED_REVIEW_REASONS
        ]
        issue_count += int(bool(failed_checks or actionable_reasons))
        expected_review_count += int(expected_review)
        row.update(
            {
                "state": claim.state.value,
                "reason_codes": claim.reason_codes,
                "deterministic_failed_checks": failed_checks,
                "entailment_judge": claim.checks.get("entailment_judge"),
                "expected_human_review": expected_review,
            }
        )

    report["rescore_at_utc"] = datetime.now(timezone.utc).isoformat()
    report["cases_with_deterministic_flags"] = issue_count
    report["cases_with_expected_human_review"] = expected_review_count
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
    )
    parser.add_argument(
        "--include-corpus",
        action="store_true",
        help="Also run every distinct fact text in the synthetic corpus",
    )
    parser.add_argument(
        "--model-id",
        help=(
            "Use an already-installed Ollama model tag for this audit; this command "
            "never downloads models"
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Run only the first N cases (useful for a quick check of another installed model)",
    )
    parser.add_argument(
        "--rescore-existing",
        type=Path,
        help="Reapply current deterministic checks to saved outputs without calling Ollama",
    )
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")
    if args.rescore_existing:
        report = rescore_existing(args.rescore_existing)
        output = args.output or args.rescore_existing.with_name(
            f"{args.rescore_existing.stem}_rescored.json"
        )
    else:
        report = evaluate(
            include_corpus=args.include_corpus,
            model_id=args.model_id,
            limit=args.limit,
        )
        output = args.output or ROOT / "eval" / "results" / "local_model_quality.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "cases"}, indent=2))
    print(f"Saved detailed synthetic outputs to {output}")


if __name__ == "__main__":
    main()
