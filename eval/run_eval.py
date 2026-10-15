"""Measure the starter extractor and deterministic checks on synthetic data."""

from __future__ import annotations

import json
import hashlib
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "eval"))

from app.models import Claim, Fact, Sentence
from app.pipeline.extract import extract_facts, validate_fact_sources
from app.pipeline.parse import parse_and_split
from app.pipeline.verify import (
    find_conflicting_medication_fact_ids,
    normalize,
    verify_claims,
)
from corrupt import build_corruption_cases

RESULT_PATH = ROOT / "eval" / "results" / "latest.json"
DETECTOR_REASONS = {
    "medication_dose_mismatch",
    "medication_frequency_mismatch",
    "medication_duration_mismatch",
    "unsupported_attribution",
    "unsupported_medication_name",
    "unsupported_numeric_detail",
    "instruction_polarity_mismatch",
    "contradictory_medication_instructions",
}


def extraction_metrics() -> dict:
    synthetic_dir = ROOT / "data" / "synthetic"
    gold_dir = ROOT / "data" / "gold"
    document_paths = sorted(synthetic_dir.glob("doc_*.txt"))
    gold: set[tuple[str, str, str]] = set()
    predicted: set[tuple[str, str, str]] = set()
    per_document: list[dict] = []
    document_set_counts: Counter[str] = Counter()
    style_metrics: dict[str, dict[str, int]] = {}

    for document_path in document_paths:
        gold_path = gold_dir / f"{document_path.stem}.json"
        if not gold_path.exists():
            raise FileNotFoundError(f"Missing gold labels for {document_path.name}")
        gold_doc = json.loads(gold_path.read_text(encoding="utf-8"))
        document_set_counts[gold_doc.get("set", "clean")] += 1
        style = "curated_narrative" if gold_doc.get("narrative_style") else "template"
        style_metrics.setdefault(style, {"documents": 0, "gold_facts": 0, "predicted_facts": 0, "exact_matches": 0})
        doc_gold = {
            (document_path.stem, item["kind"], normalize(item["text_en"]))
            for item in gold_doc["facts"]
        }
        document_text = document_path.read_text(encoding="utf-8")
        predicted_facts = extract_facts(parse_and_split(document_text))
        doc_predicted = {
            (document_path.stem, fact.kind, normalize(fact.text_en))
            for fact in predicted_facts
        }
        gold.update(doc_gold)
        predicted.update(doc_predicted)
        style_metrics[style]["documents"] += 1
        style_metrics[style]["gold_facts"] += len(doc_gold)
        style_metrics[style]["predicted_facts"] += len(doc_predicted)
        style_metrics[style]["exact_matches"] += len(doc_gold & doc_predicted)
        per_document.append(
            {
                "document_id": gold_doc["document_id"],
                "gold_fact_count": len(doc_gold),
                "predicted_fact_count": len(doc_predicted),
                "exact_fact_matches": len(doc_gold & doc_predicted),
                "style": style,
            }
        )

    true_positives = len(gold & predicted)
    precision = true_positives / len(predicted) if predicted else 0.0
    recall = true_positives / len(gold) if gold else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    source_link_matches = 0
    source_link_total = 0
    for document_path in document_paths:
        gold_path = gold_dir / f"{document_path.stem}.json"
        gold_doc = json.loads(gold_path.read_text(encoding="utf-8"))
        expected_links = {
            (item["kind"], normalize(item["text_en"])): item["source_ids"]
            for item in gold_doc["facts"]
        }
        sentences = parse_and_split(document_path.read_text(encoding="utf-8"))
        predicted_facts = validate_fact_sources(extract_facts(sentences), sentences)
        for fact in predicted_facts:
            source_link_total += 1
            if expected_links.get((fact.kind, normalize(fact.text_en))) == fact.source_ids:
                source_link_matches += 1

    for metrics in style_metrics.values():
        tp = metrics["exact_matches"]
        metrics["exact_precision"] = round(tp / metrics["predicted_facts"], 4) if metrics["predicted_facts"] else 0.0
        metrics["exact_recall"] = round(tp / metrics["gold_facts"], 4) if metrics["gold_facts"] else 0.0
        p, r = metrics["exact_precision"], metrics["exact_recall"]
        metrics["exact_f1"] = round(2 * p * r / (p + r), 4) if p + r else 0.0
    manifest_hash = hashlib.sha256()
    for path in sorted([*document_paths, *gold_dir.glob("doc_*.json")]):
        manifest_hash.update(path.name.encode())
        manifest_hash.update(path.read_bytes())
    return {
        "document_count": len(document_paths),
        "document_set_counts": dict(document_set_counts),
        "style_metrics": style_metrics,
        "dataset_sha256": manifest_hash.hexdigest(),
        "gold_fact_count": len(gold),
        "predicted_fact_count": len(predicted),
        "true_positives": true_positives,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "source_link_match_count": source_link_matches,
        "source_link_count": source_link_total,
        "source_link_accuracy": (
            source_link_matches / source_link_total if source_link_total else 0.0
        ),
        "per_document": per_document,
    }


def evaluate_corruptions() -> dict:
    cases = build_corruption_cases()
    caught = 0
    clean_claim_count = 0
    clean_claim_flags = 0
    clean_states: Counter[str] = Counter()
    corrupted_states: Counter[str] = Counter()
    clean_priority_scores: list[float] = []
    corrupted_priority_scores: list[float] = []
    case_results: list[dict] = []
    false_negative_ids: list[str] = []
    false_alarm_ids: list[str] = []

    for case in cases:
        sentences = [Sentence.model_validate(row) for row in case["source_sentences"]]
        facts = [Fact.model_validate(row) for row in case["facts"]]
        claim_data = case["claim"]
        mutated_claim = Claim(
            **claim_data,
            text=case["corrupted_text"],
        )
        verify_claims([mutated_claim], sentences, facts)
        corrupted_states[mutated_claim.state.value] += 1
        if mutated_claim.review_priority_score is not None:
            corrupted_priority_scores.append(mutated_claim.review_priority_score)
        reason_matched = case["expected_reason"] in mutated_claim.reason_codes
        caught += int(reason_matched)
        if not reason_matched:
            false_negative_ids.append(case["id"])

        clean_flagged = None
        if not case["clean_has_conflict"]:
            clean_claim = Claim(
                **claim_data,
                text=case["clean_text"],
            )
            verify_claims([clean_claim], sentences, facts)
            clean_states[clean_claim.state.value] += 1
            if clean_claim.review_priority_score is not None:
                clean_priority_scores.append(clean_claim.review_priority_score)
            clean_flagged = bool(DETECTOR_REASONS.intersection(clean_claim.reason_codes))
            clean_claim_count += 1
            clean_claim_flags += int(clean_flagged)
            if clean_flagged:
                false_alarm_ids.append(case["id"])

        case_results.append(
            {
                "id": case["id"],
                "expected_reason": case["expected_reason"],
                "actual_reasons": mutated_claim.reason_codes,
                "expected_reason_detected": reason_matched,
                "clean_claim_flagged": clean_flagged,
                "corrupted_state": mutated_claim.state.value,
                "corrupted_review_priority_score": mutated_claim.review_priority_score,
                "clean_review_priority_score": clean_claim.review_priority_score if not case["clean_has_conflict"] else None,
            }
        )

    def summarize(scores: list[float]) -> dict:
        return {
            "count": len(scores),
            "mean": round(sum(scores) / len(scores), 4) if scores else None,
        }

    return {
        "corrupted_case_count": len(cases),
        "expected_reason_detected_count": caught,
        "expected_reason_detection_rate": caught / len(cases) if cases else 0.0,
        "false_negative_count": len(false_negative_ids),
        "false_negative_case_ids": false_negative_ids,
        "clean_claim_count": clean_claim_count,
        "clean_claim_flagged_count": clean_claim_flags,
        "false_alarm_count": len(false_alarm_ids),
        "false_alarm_case_ids": false_alarm_ids,
        "clean_claim_false_flag_rate": (
            clean_claim_flags / clean_claim_count if clean_claim_count else 0.0
        ),
        "clean_claim_routing_counts": dict(clean_states),
        "corrupted_claim_routing_counts": dict(corrupted_states),
        "review_priority_score": {
            "clean_claims": summarize(clean_priority_scores),
            "corrupted_claims": summarize(corrupted_priority_scores),
            "scope_note": "This score only orders the human review queue; it is not a probability or model-quality metric.",
        },
        "cases": case_results,
    }


def evaluate_trap_documents() -> dict:
    """Measure configured cross-fact medication-conflict detection on trap docs."""
    gold_dir = ROOT / "data" / "gold"
    synthetic_dir = ROOT / "data" / "synthetic"
    traps_detected = 0
    clean_false_flags = 0
    trap_count = 0
    clean_count = 0
    trap_by_type: dict[str, dict[str, int]] = {}

    for gold_path in sorted(gold_dir.glob("doc_*.json")):
        gold_doc = json.loads(gold_path.read_text(encoding="utf-8"))
        document_path = synthetic_dir / f"{gold_path.stem}.txt"
        sentences = parse_and_split(document_path.read_text(encoding="utf-8"))
        facts = extract_facts(sentences)
        detected = bool(find_conflicting_medication_fact_ids(facts))
        if gold_doc.get("set") == "trap":
            trap_count += 1
            traps_detected += int(detected)
            trap_type = gold_doc.get("trap_type", "stop_continue_conflict")
            counts = trap_by_type.setdefault(trap_type, {"count": 0, "detected": 0})
            counts["count"] += 1
            counts["detected"] += int(detected)
        else:
            clean_count += 1
            clean_false_flags += int(detected)

    by_type = {
        trap_type: {
            **counts,
            "detection_rate": counts["detected"] / counts["count"],
        }
        for trap_type, counts in trap_by_type.items()
    }
    return {
        "trap_document_count": trap_count,
        "trap_detected_count": traps_detected,
        "trap_detection_rate": traps_detected / trap_count if trap_count else 0.0,
        "trap_detection_by_type": by_type,
        "clean_document_count": clean_count,
        "clean_conflict_false_flag_count": clean_false_flags,
        "clean_conflict_false_flag_rate": (
            clean_false_flags / clean_count if clean_count else 0.0
        ),
    }


def main() -> None:
    extraction = extraction_metrics()
    report = {
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "synthetic_data_only": True,
        "scope_note": (
            f"Starter corpus: {extraction['document_count']} synthetic documents "
            "and controlled heuristic cases. Results are stratified by template versus curated narrative style. "
            "These measurements do not establish clinical performance."
        ),
        "extraction": extraction,
        "trap_documents": evaluate_trap_documents(),
        "corruption_checks": evaluate_corruptions(),
    }
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"Saved results to {RESULT_PATH}")


if __name__ == "__main__":
    main()
