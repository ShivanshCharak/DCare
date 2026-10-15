"""Score qualified human labels for the held-out review set.

This script intentionally requires completed reviewer labels and saved system
predictions. It never treats author-created expected labels as human results.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LABEL_FIELDS = {
    "unsupported_addition": "unsupported_addition_yes_no",
    "missing_detail": "missing_detail_yes_no",
    "medication_change": "medication_change_yes_no",
    "wrong_source_link": "wrong_source_link_yes_no",
}


def score(labels_path: Path, predictions_path: Path, output_path: Path) -> dict:
    predictions = json.loads(predictions_path.read_text(encoding="utf-8"))
    if predictions.get("model_id") != "qwen3:1.7b" or predictions.get("model_digest") != "8f68893c685c3ddff2aa3fffce2aa60a30bb2da65ca488b61fff134a4d1730e7":
        raise ValueError("Predictions must identify the pinned qwen3:1.7b judge digest.")
    by_id = {row["case_id"]: row for row in predictions.get("cases", [])}
    with labels_path.open(newline="", encoding="utf-8-sig") as stream:
        labels = list(csv.DictReader(stream))
    if not labels:
        raise ValueError("Reviewer label file is empty.")
    if any(not row.get("reviewer_id", "").strip() or not row.get("reviewer_qualification", "").strip() for row in labels):
        raise ValueError("Every row needs reviewer_id and reviewer_qualification before scoring.")

    results = {}
    for label_name, field in LABEL_FIELDS.items():
        counts = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
        for row in labels:
            answer = row.get(field, "").strip().lower()
            if answer not in {"yes", "no"}:
                raise ValueError(f"{row.get('case_id')}: {field} must be yes or no.")
            case = by_id.get(row["case_id"])
            if case is None:
                raise ValueError(f"Missing system prediction for {row['case_id']}.")
            predicted = label_name in case.get("deterministic_flags", [])
            actual = answer == "yes"
            counts[{(True, True): "tp", (True, False): "fp", (False, True): "fn", (False, False): "tn"}[(predicted, actual)]] += 1
        reviewed_positive = counts["tp"] + counts["fn"]
        reviewed_negative = counts["fp"] + counts["tn"]
        results[label_name] = {
            **counts,
            "miss_rate": counts["fn"] / reviewed_positive if reviewed_positive else None,
            "false_alarm_rate": counts["fp"] / reviewed_negative if reviewed_negative else None,
        }

    judged = []
    for row in labels:
        case = by_id[row["case_id"]]
        human = row.get("overall_supported_yes_no", "").strip().lower()
        verdict = case.get("entailment_judge")
        if human not in {"yes", "no"}:
            raise ValueError(f"{row.get('case_id')}: overall_supported_yes_no must be yes or no.")
        if verdict in {"supported", "unsupported"}:
            judged.append({
                "human_supported": human == "yes",
                "judge_supported": verdict == "supported",
                "case_id": row["case_id"],
            })
    agreement = sum(item["human_supported"] == item["judge_supported"] for item in judged)
    judge_counts = {"true_positive": 0, "false_positive": 0, "false_negative": 0, "true_negative": 0}
    judge_false_positives: list[str] = []
    judge_false_negatives: list[str] = []
    for item in judged:
        # Treat "unsupported" as the positive class: a false negative is an
        # unfaithful claim the judge incorrectly accepts as supported.
        human_unsupported = not item["human_supported"]
        judge_unsupported = not item["judge_supported"]
        category = {
            (True, True): "true_positive",
            (False, True): "false_positive",
            (True, False): "false_negative",
            (False, False): "true_negative",
        }[(human_unsupported, judge_unsupported)]
        judge_counts[category] += 1
        if category == "false_positive":
            judge_false_positives.append(item["case_id"])
        elif category == "false_negative":
            judge_false_negatives.append(item["case_id"])
    report = {
        "scope": "held-out synthetic discharge-summary claims with qualified human adjudication",
        "model_id": predictions["model_id"],
        "human_label_count": len(labels),
        "reviewers": sorted({row["reviewer_id"].strip() for row in labels}),
        "reviewer_qualifications": sorted({row["reviewer_qualification"].strip() for row in labels}),
        "deterministic_error_metrics": results,
        "llm_judge_human_agreement": {
            "eligible_cases": len(judged),
            "agreement_count": agreement,
            "agreement_rate": agreement / len(judged) if judged else None,
            "uncertain_or_missing_judge_cases": len(labels) - len(judged),
            "confusion_counts": judge_counts,
            "false_alarm_rate": (
                judge_counts["false_positive"] /
                (judge_counts["false_positive"] + judge_counts["true_negative"])
                if judge_counts["false_positive"] + judge_counts["true_negative"] else None
            ),
            "miss_rate": (
                judge_counts["false_negative"] /
                (judge_counts["false_negative"] + judge_counts["true_positive"])
                if judge_counts["false_negative"] + judge_counts["true_positive"] else None
            ),
            "false_positive_case_ids": judge_false_positives,
            "false_negative_case_ids": judge_false_negatives,
        },
        "limitations": ["Synthetic cases do not establish clinical performance or safety.", "Agreement is measured only on cases with supported/unsupported human and judge labels."],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", type=Path, default=ROOT / "eval/heldout/reviewer_labels.csv")
    parser.add_argument("--predictions", type=Path, default=ROOT / "eval/heldout/system_predictions.json")
    parser.add_argument("--output", type=Path, default=ROOT / "eval/heldout/human_evaluation.json")
    args = parser.parse_args()
    print(json.dumps(score(args.labels, args.predictions, args.output), indent=2))
