"""Run a multilingual Sarvam-1 translation benchmark and create a review sheet.

The automated checks cover output availability, target script, and verbatim
preservation of selected names and numeric details. Translation meaning and
readability require qualified human review; blank ratings are not scores.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import settings
from app.models import Fact
from app.pipeline.translate import (
    LANGUAGES,
    SARVAM_TRANSLATION_MODEL,
    _protected_tokens,
    _translate_text,
)

REVIEW_FIELDS = (
    "semantic_fidelity_1_5", "critical_details_preserved_yes_no",
    "omissions_yes_no", "additions_yes_no", "readability_1_5",
    "naturalness_1_5", "review_decision", "reviewer_id",
    "reviewer_qualification", "reviewed_at", "review_notes",
)
TARGET_LANGUAGES = tuple(code for code in LANGUAGES if code != "en")


def _model_digest() -> str:
    parsed = urlparse(settings.llm_base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError(f"Invalid Ollama endpoint: {settings.llm_base_url!r}")
    tags_url = f"{parsed.scheme}://{parsed.netloc}/api/tags"
    with urlopen(tags_url, timeout=5) as response:
        payload = json.loads(response.read().decode("utf-8"))
    installed = {model.get("name"): model for model in payload.get("models", [])}
    model = installed.get(SARVAM_TRANSLATION_MODEL)
    if model is None:
        model = installed.get(f"{SARVAM_TRANSLATION_MODEL}:latest")
    if model is None:
        raise RuntimeError(
            f"Sarvam model {SARVAM_TRANSLATION_MODEL!r} is not installed at {tags_url}. "
            f"Installed tags: {sorted(installed)}"
        )
    return model.get("digest", "")


def run(cases_path: Path, json_path: Path, csv_path: Path, limit: int | None = None) -> dict:
    digest = _model_digest()
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    if limit is not None:
        cases = cases[:limit]

    rows = []
    total = len(cases) * len(TARGET_LANGUAGES)
    for language in TARGET_LANGUAGES:
        for case in cases:
            fact = Fact(
                id=f"F-{case['id']}",
                kind="medication" if case["category"] == "medication" else "appointment",
                text_en=case["source"], attrs={}, source_ids=[f"S-{case['id']}"],
            )
            protected = sorted(_protected_tokens(case["source"], [fact]), key=str.casefold)
            output = ""
            error = ""
            try:
                output = _translate_text(case["source"], language)
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
            missing = [token for token in protected if token.casefold() not in output.casefold()]
            format_issues = []
            if "</s>" in output or "English:" in output:
                format_issues.append("echoed_prompt_or_example")
            rows.append({
                "case_id": case["id"], "language": language,
                "language_name": LANGUAGES[language], "category": case["category"],
                "source": case["source"], "output": output,
                "translation_succeeded": bool(output) and not error and not format_issues,
                "protected_tokens": protected, "missing_protected_tokens": missing,
                "token_preservation_passed": bool(output) and not missing and not error and not format_issues,
                "format_issues": format_issues,
                "error": error,
            })
            print(f"[{len(rows)}/{total}] {LANGUAGES[language]} / {case['id']}: "
                  f"{'ok' if output and not error else 'failed'}", flush=True)

    for row in rows:
        row["human_review"] = {name: "" for name in REVIEW_FIELDS}
    report = {
        "scope": "project-authored multilingual Sarvam-1 translation benchmark",
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "data_provenance": "Project-authored examples; no patient records; not independently translated or clinically reviewed.",
        "model_id": SARVAM_TRANSLATION_MODEL,
        "model_digest": digest,
        "case_set_sha256": hashlib.sha256(cases_path.read_bytes()).hexdigest(),
        "case_count": len(rows),
        "case_counts_by_language": {
            code: sum(row["language"] == code for row in rows)
            for code in TARGET_LANGUAGES
        },
        "translation_success_count": sum(row["translation_succeeded"] for row in rows),
        "token_preservation_pass_count": sum(row["token_preservation_passed"] for row in rows),
        "token_preservation_by_language": {
            code: {
                "translated_count": sum(row["language"] == code and row["translation_succeeded"] for row in rows),
                "passed": sum(row["language"] == code and row["token_preservation_passed"] for row in rows),
            }
            for code in TARGET_LANGUAGES
        },
        "format_issue_count": sum(bool(row["format_issues"]) for row in rows),
        "human_quality_measured": False,
        "cases": rows,
        "limitations": [
            "Synthetic cases are not an independently authored clinical benchmark.",
            "Script and token checks do not measure translation meaning, readability, or clinical safety.",
            "Have qualified bilingual reviewers rate every language before making quality claims.",
        ],
    }
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "case_id", "language", "language_name", "category", "source", "output",
        "translation_succeeded", "protected_tokens", "missing_protected_tokens",
        "token_preservation_passed", "format_issues", "error", *REVIEW_FIELDS,
    ]
    with csv_path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                **{key: json.dumps(row[key], ensure_ascii=False) if isinstance(row[key], list) else row[key]
                   for key in fields if key in row},
                **row["human_review"],
            })
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, default=ROOT / "eval/sarvam_translation_cases.json")
    parser.add_argument("--json", type=Path, default=ROOT / "eval/results/sarvam_multilingual_benchmark.json")
    parser.add_argument("--csv", type=Path, default=ROOT / "eval/results/sarvam_multilingual_review.csv")
    parser.add_argument("--limit", type=int, help="Run only the first N source cases per language.")
    args = parser.parse_args()
    result = run(args.cases, args.json, args.csv, args.limit)
    print(f"Saved {result['case_count']} Sarvam translations; "
          f"{result['token_preservation_pass_count']} passed protected-token checks.")
