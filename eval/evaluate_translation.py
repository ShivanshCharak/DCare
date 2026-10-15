"""Run a synthetic translation audit and prepare a bilingual human review sheet.

Token preservation is reported separately from meaning. No human quality score
is reported until reviewer metadata and ratings have been filled in.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.models import Claim, Fact, State
from app.pipeline.translate import _protected_tokens, translate_claims
from app.config import settings

RATING_FIELDS = (
    "semantic_fidelity_1_5", "critical_details_preserved_yes_no",
    "omissions_yes_no", "additions_yes_no", "readability_1_5",
    "naturalness_1_5", "review_decision", "error_categories",
    "reviewer_corrected_translation", "reviewer_id", "reviewer_qualification",
    "reviewed_at", "review_notes",
)
REQUIRED_REVIEW_FIELDS = (
    "semantic_fidelity_1_5", "critical_details_preserved_yes_no",
    "omissions_yes_no", "additions_yes_no", "readability_1_5",
    "naturalness_1_5", "review_decision", "reviewer_id",
    "reviewer_qualification", "reviewed_at",
)
PINNED_MODEL_DIGESTS = {
    "qwen3:1.7b": "8f68893c685c3ddff2aa3fffce2aa60a30bb2da65ca488b61fff134a4d1730e7",
}


def _load_adjudications(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8-sig") as stream:
        # Carry forward ratings only. In particular, never let stale source or
        # output cells overwrite the current model output when the sheet is rebuilt.
        return {
            row.get("row_id", ""): {
                **{name: row.get(name, "") for name in RATING_FIELDS},
                "_case_id": row.get("case_id", ""),
                "_output": row.get("output", ""),
            }
            for row in csv.DictReader(stream)
        }


def _is_complete_review(row: dict) -> bool:
    required = all(str(row.get(name, "")).strip() for name in REQUIRED_REVIEW_FIELDS)
    if not required:
        return False
    try:
        scores = [int(row[name]) for name in ("semantic_fidelity_1_5", "readability_1_5", "naturalness_1_5")]
    except (TypeError, ValueError):
        return False
    return all(1 <= score <= 5 for score in scores) and all(
        row[name].strip().lower() in {"yes", "no"}
        for name in ("critical_details_preserved_yes_no", "omissions_yes_no", "additions_yes_no")
    ) and row.get("review_decision", "").strip().lower() in {"acceptable", "revise", "reject"} and (
        row.get("review_decision", "").strip().lower() == "acceptable"
        or bool(row.get("reviewer_corrected_translation", "").strip() or row.get("review_notes", "").strip())
    )


def _review_summary(rows: list[dict]) -> tuple[list[dict], dict | None]:
    reviews = [row["human_review"] for row in rows if _is_complete_review(row.get("human_review", {}))]
    if not reviews:
        return reviews, None

    def numeric_mean(field: str) -> float | None:
        values = [float(review[field]) for review in reviews if review[field].strip()]
        return round(sum(values) / len(values), 3) if values else None

    summary = {
        "complete_review_count": len(reviews),
        "mean_semantic_fidelity_1_5": numeric_mean("semantic_fidelity_1_5"),
        "mean_readability_1_5": numeric_mean("readability_1_5"),
        "mean_naturalness_1_5": numeric_mean("naturalness_1_5"),
        "critical_details_preserved_rate": sum(review["critical_details_preserved_yes_no"].strip().lower() == "yes" for review in reviews) / len(reviews),
        "omission_rate": sum(review["omissions_yes_no"].strip().lower() == "yes" for review in reviews) / len(reviews),
        "addition_rate": sum(review["additions_yes_no"].strip().lower() == "yes" for review in reviews) / len(reviews),
        "review_decisions": {
            decision: sum(review["review_decision"].strip().lower() == decision for review in reviews)
            for decision in ("acceptable", "revise", "reject")
        },
        "cases_with_corrected_translation": sum(bool(review.get("reviewer_corrected_translation", "").strip()) for review in reviews),
        "reviewers": sorted({review["reviewer_id"].strip() for review in reviews}),
        "qualification_records": sorted({review["reviewer_qualification"].strip() for review in reviews}),
        "by_language": {
            lang: {
                "review_count": len(group := [
                    row["human_review"] for row in rows
                    if row.get("language") == lang and _is_complete_review(row.get("human_review", {}))
                ]),
                "mean_semantic_fidelity_1_5": round(sum(int(review["semantic_fidelity_1_5"]) for review in group) / len(group), 3) if group else None,
                "critical_details_preserved_rate": sum(review["critical_details_preserved_yes_no"].strip().lower() == "yes" for review in group) / len(group) if group else None,
            } for lang in ("hi",)
        },
    }
    return reviews, summary


def _write_adjudication_sheet(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["row_id", "case_id", "language", "category", "source", "output", *RATING_FIELDS]
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                **{key: row.get(key, "") for key in ("row_id", "case_id", "language", "category", "source", "output")},
                **row.get("human_review", {}),
            })


def summarize_existing_reviews(report_path: Path, adjudication_path: Path) -> dict:
    """Attach ratings to the exact audited output and summarize without rerunning translation."""
    report = json.loads(report_path.read_text(encoding="utf-8"))
    saved = _load_adjudications(adjudication_path)
    by_case = {row.get("_case_id"): row for row in saved.values()}
    for case in report.get("cases", []):
        old_row_id = case.get("row_id")
        review = saved.get(old_row_id) or by_case.get(case.get("case_id")) or {}
        # A rating belongs only to the exact output the reviewer saw.
        if review.get("_output") != case.get("output"):
            review = {}
        output_fingerprint = hashlib.sha256(case.get("output", "").encode("utf-8")).hexdigest()[:12]
        case["row_id"] = f"{case['case_id']}:{report['model_id']}:{output_fingerprint}"
        case["human_review"] = {name: review.get(name, "") for name in RATING_FIELDS}
    complete, summary = _review_summary(report["cases"])
    report["semantic_quality_measured"] = bool(complete)
    report["human_review_complete_row_count"] = len(complete)
    report["human_quality_summary"] = summary
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_adjudication_sheet(adjudication_path, report["cases"])
    return report


def check_ollama_health() -> str:
    """Fail before producing artifacts unless Ollama is up with the pinned tag."""
    parsed = urlparse(settings.llm_base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError(f"Invalid Ollama endpoint in LLM_BASE_URL: {settings.llm_base_url!r}")
    tags_url = f"{parsed.scheme}://{parsed.netloc}/api/tags"
    try:
        with urlopen(tags_url, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Ollama health check failed at {tags_url}: {exc}") from exc
    installed = {model.get("name"): model for model in payload.get("models", [])}
    if settings.model_id not in installed:
        raise RuntimeError(
            f"Ollama is reachable at {tags_url}, but pinned model tag "
            f"{settings.model_id!r} is not installed. Installed tags: {sorted(installed)}"
        )
    digest = installed[settings.model_id].get("digest", "")
    expected_digest = PINNED_MODEL_DIGESTS.get(settings.model_id)
    if expected_digest and digest != expected_digest:
        raise RuntimeError(
            f"Ollama tag {settings.model_id!r} has digest {digest!r}; "
            f"expected pinned digest {expected_digest!r}."
        )
    return digest


def run(output: Path, cases_path: Path, adjudication_path: Path) -> dict:
    model_digest = check_ollama_health()
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    existing_reviews = _load_adjudications(adjudication_path)
    existing_by_case = {row.get("_case_id"): row for row in existing_reviews.values()}
    rows = []
    for case in cases:
        fact_kind = "appointment" if case["category"] == "follow_up" else case["category"]
        fact = Fact(
            id=f"F-{case['id']}", kind=fact_kind, text_en=case["source"],
            attrs={}, source_ids=[f"S-{case['id']}"],
        )
        claim = Claim(
            id=f"C-{case['id']}", text=case["source"], language="en",
            fact_ids=[fact.id], source_ids=fact.source_ids,
            state=State.NEEDS_CLINICIAN,
        )
        translate_claims([claim], [fact], case["language"])
        required = sorted(_protected_tokens(case["source"], [fact]), key=str.casefold)
        succeeded = claim.language == case["language"]
        missing = [token for token in required if token.casefold() not in claim.text.casefold()] if succeeded else None
        output_fingerprint = hashlib.sha256(claim.text.encode("utf-8")).hexdigest()[:12]
        row_id = f"{case['id']}:{settings.model_id}:{output_fingerprint}"
        saved_review = existing_reviews.get(row_id) or existing_by_case.get(case["id"]) or {}
        if saved_review.get("_output") != claim.text:
            saved_review = {}
        rows.append({
            "row_id": row_id, "case_id": case["id"], "language": case["language"],
            "category": case["category"], "source": case["source"], "output": claim.text,
            "required_verbatim_tokens": required, "missing_tokens": missing,
            "translation_succeeded": succeeded,
            "token_preservation_passed": succeeded and not missing,
            "translation_check": claim.checks.get("translation"),
            "routing_state": claim.state.value,
            "review_priority_score": claim.review_priority_score,
            "human_review": {name: saved_review.get(name, "") for name in RATING_FIELDS},
        })

    complete_reviews, human_quality_summary = _review_summary(rows)
    report = {
        "scope": "independently authored synthetic translation cases; local-model output audit",
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "synthetic_data_only": True,
        "model_id": settings.model_id,
        "model_digest": model_digest,
        "case_set_sha256": hashlib.sha256(cases_path.read_bytes()).hexdigest(),
        "case_count": len(rows),
        "case_counts_by_language": {
            lang: sum(row["language"] == lang for row in rows) for lang in ("hi",)
        },
        "translation_success_count": sum(row["translation_succeeded"] for row in rows),
        "translation_failure_count": sum(not row["translation_succeeded"] for row in rows),
        "token_preservation_by_language": {
            lang: {
                "translated_count": sum(row["language"] == lang and row["translation_succeeded"] for row in rows),
                "passed": sum(row["language"] == lang and row["token_preservation_passed"] for row in rows),
                "pass_rate": (
                    sum(row["language"] == lang and row["token_preservation_passed"] for row in rows)
                    / sum(row["language"] == lang and row["translation_succeeded"] for row in rows)
                    if any(row["language"] == lang and row["translation_succeeded"] for row in rows)
                    else None
                ),
            } for lang in ("hi",)
        },
        "token_preservation_by_category": {
            category: {
                "translated_count": sum(row["category"] == category and row["translation_succeeded"] for row in rows),
                "passed": sum(row["category"] == category and row["token_preservation_passed"] for row in rows),
                "pass_rate": (
                    sum(row["category"] == category and row["token_preservation_passed"] for row in rows)
                    / sum(row["category"] == category and row["translation_succeeded"] for row in rows)
                    if any(row["category"] == category and row["translation_succeeded"] for row in rows)
                    else None
                ),
            } for category in sorted({row["category"] for row in rows})
        },
        "semantic_quality_measured": bool(complete_reviews),
        "human_review_complete_row_count": len(complete_reviews),
        "token_preservation_pass_count": sum(row["token_preservation_passed"] for row in rows),
        "token_preservation_pass_rate": (
            sum(row["token_preservation_passed"] for row in rows) / sum(row["translation_succeeded"] for row in rows)
            if any(row["translation_succeeded"] for row in rows) else None
        ),
        "human_quality_summary": human_quality_summary,
        "cases": rows,
        "limitations": [
            "Cases are synthetic and authored separately from the templated document corpus.",
            "Token preservation does not measure translation meaning or readability.",
            "Human ratings require qualified Hindi reviewers; blank ratings are not evidence.",
            "This audit does not establish clinical performance or safety.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_adjudication_sheet(adjudication_path, rows)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("eval/results/translation_audit.json"))
    parser.add_argument("--cases", type=Path, default=ROOT / "eval/translation_cases.json")
    parser.add_argument("--adjudication", type=Path, default=Path("eval/results/translation_adjudication.csv"))
    parser.add_argument(
        "--summarize-reviews", action="store_true",
        help="Summarize the saved reviewer CSV without calling Ollama or regenerating translations.",
    )
    args = parser.parse_args()
    if args.summarize_reviews:
        result = summarize_existing_reviews(args.output, args.adjudication)
        print(f"Updated review summary from {result['human_review_complete_row_count']} completed human ratings; translations were not regenerated.")
    else:
        result = run(args.output, args.cases, args.adjudication)
        print(f"Saved {result['case_count']} translation cases. Human semantic ratings recorded: {result['human_review_complete_row_count']}.")
