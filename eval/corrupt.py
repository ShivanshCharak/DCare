"""Create a small, deterministic set of synthetic corrupted claims."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT / "eval" / "results" / "corruptions.json"


def _fact(fact_id: str, kind: str, text: str, source_id: str) -> dict:
    return {
        "id": fact_id,
        "kind": kind,
        "text_en": text,
        "attrs": {},
        "source_ids": [source_id],
    }


def _case(
    case_id: str,
    source_sentences: list[dict],
    facts: list[dict],
    fact_id: str,
    source_id: str,
    clean_text: str,
    corrupted_text: str,
    expected_reason: str,
    *,
    clean_has_conflict: bool = False,
) -> dict:
    return {
        "id": case_id,
        "source_sentences": source_sentences,
        "facts": facts,
        "claim": {
            "id": "C1",
            "language": "en",
            "fact_ids": [fact_id],
            "source_ids": [source_id],
        },
        "clean_text": clean_text,
        "corrupted_text": corrupted_text,
        "expected_reason": expected_reason,
        "clean_has_conflict": clean_has_conflict,
    }


def build_corruption_cases() -> list[dict]:
    """Return controlled changes with an expected verifier reason per case."""
    return [
        _case(
            "dose_changed",
            [{"id": "S1", "text": "Take amlodipine 5 mg once daily.", "section": "medications"}],
            [_fact("F1", "medication", "Take amlodipine 5 mg once daily.", "S1")],
            "F1", "S1", "Take amlodipine 5 mg once daily.",
            "Take amlodipine 50 mg once daily.", "medication_dose_mismatch",
        ),
        _case(
            "frequency_changed",
            [{"id": "S1", "text": "Take amlodipine 5 mg once daily.", "section": "medications"}],
            [_fact("F1", "medication", "Take amlodipine 5 mg once daily.", "S1")],
            "F1", "S1", "Take amlodipine 5 mg once daily.",
            "Take amlodipine 5 mg twice daily.", "medication_frequency_mismatch",
        ),
        _case(
            "unsupported_known_medication_name",
            [{"id": "S1", "text": "Take amlodipine 5 mg once daily.", "section": "medications"}],
            [_fact("F1", "medication", "Take amlodipine 5 mg once daily.", "S1")],
            "F1", "S1", "Take amlodipine 5 mg once daily.",
            "Take amoxicillin and amlodipine 5 mg once daily.", "unsupported_medication_name",
        ),
        _case(
            "follow_up_timeframe_changed",
            [{"id": "S1", "text": "Attend your follow-up appointment in 7 days.", "section": "follow_up"}],
            [_fact("F1", "appointment", "Attend your follow-up appointment in 7 days.", "S1")],
            "F1", "S1", "Attend your follow-up appointment in 7 days.",
            "Attend your follow-up appointment in 30 days.", "unsupported_numeric_detail",
        ),
        _case(
            "date_changed",
            [{"id": "S1", "text": "Your appointment is on 10/20/2026.", "section": "follow_up"}],
            [_fact("F1", "appointment", "Your appointment is on 10/20/2026.", "S1")],
            "F1", "S1", "Your appointment is on 10/20/2026.",
            "Your appointment is on 10/21/2026.", "unsupported_numeric_detail",
        ),
        _case(
            "negation_dropped",
            [{"id": "S1", "text": "Do not take aspirin.", "section": "medications"}],
            [_fact("F1", "medication", "Do not take aspirin.", "S1")],
            "F1", "S1", "Do not take aspirin.",
            "Take aspirin.", "instruction_polarity_mismatch",
        ),
        _case(
            "unsupported_clinician_attribution",
            [{"id": "S1", "text": "Pneumonia was diagnosed.", "section": "diagnosis"}],
            [_fact("F1", "diagnosis", "Pneumonia was diagnosed.", "S1")],
            "F1", "S1", "Pneumonia was diagnosed.",
            "The doctor told the patient they have pneumonia.", "unsupported_attribution",
        ),
        _case(
            "high_alert_stop_continue_conflict",
            [
                {"id": "S1", "text": "Stop taking warfarin.", "section": "medications"},
                {"id": "S2", "text": "Continue taking warfarin.", "section": "medications"},
            ],
            [
                _fact("F1", "medication", "Stop taking warfarin.", "S1"),
                _fact("F2", "medication", "Continue taking warfarin.", "S2"),
            ],
            "F1", "S1", "Stop taking warfarin.",
            "Stop taking warfarin.", "contradictory_medication_instructions",
            clean_has_conflict=True,
        ),
        _case(
            "medication_duration_changed",
            [{"id": "S1", "text": "Take amoxicillin 500 mg twice daily for 5 days.", "section": "medications"}],
            [_fact("F1", "medication", "Take amoxicillin 500 mg twice daily for 5 days.", "S1")],
            "F1", "S1", "Take amoxicillin 500 mg twice daily for 5 days.",
            "Take amoxicillin 500 mg twice daily for 10 days.", "medication_duration_mismatch",
        ),
        _case(
            "as_needed_instruction_dropped",
            [{"id": "S1", "text": "Take morphine 2 mg every 6 hours as needed.", "section": "medications"}],
            [_fact("F1", "medication", "Take morphine 2 mg every 6 hours as needed.", "S1")],
            "F1", "S1", "Take morphine 2 mg every 6 hours as needed.",
            "Take morphine 2 mg every 6 hours.", "medication_frequency_mismatch",
        ),
        _case(
            "continue_instruction_dropped",
            [{"id": "S1", "text": "Continue taking lisinopril 10 mg once daily.", "section": "medications"}],
            [_fact("F1", "medication", "Continue taking lisinopril 10 mg once daily.", "S1")],
            "F1", "S1", "Continue taking lisinopril 10 mg once daily.",
            "Take lisinopril 10 mg once daily.", "instruction_polarity_mismatch",
        ),
        _case(
            "restriction_threshold_changed",
            [{"id": "S1", "text": "Do not lift objects heavier than 5 kg until review.", "section": "restrictions"}],
            [_fact("F1", "restriction", "Do not lift objects heavier than 5 kg until review.", "S1")],
            "F1", "S1", "Do not lift objects heavier than 5 kg until review.",
            "Do not lift objects heavier than 10 kg until review.", "unsupported_numeric_detail",
        ),
    ]


def main() -> None:
    cases = build_corruption_cases()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(cases, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(cases)} synthetic corruption cases to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
