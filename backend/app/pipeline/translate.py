"""Local-model translation with source-linked conservative review handling."""

from __future__ import annotations

import re
import json

from ..config import settings
from ..llm_client import chat_completion
from ..models import Claim, Fact, State
from .entailment import check_claim_entailment

LANGUAGES = {"hi": "Hindi"}
JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["pass", "revise"]},
        "issues": {"type": "array", "items": {"type": "string"}},
        "corrected_translation": {"type": "string"},
    },
    "required": ["verdict", "issues", "corrected_translation"],
    "additionalProperties": False,
}


def _judge_translation(source: str, translated: str) -> tuple[str, list[str]]:
    response = chat_completion(
        model=settings.translation_judge_model_id,
        messages=[
            {"role": "system", "content": (
                "Review a Hindi translation of an English hospital discharge instruction. "
                "Check that every meaning is preserved, nothing is omitted or added, and the Hindi is clear and natural. "
                "Pay special attention to negation, medication instructions, timing, warnings, and follow-up. "
                "If there is any issue, return verdict revise and provide a complete corrected Hindi translation. "
                "Do not invent facts. If the translation is accurate, return pass and an empty corrected_translation. "
                "This is a conservative screening check, not clinical approval."
            )},
            {"role": "user", "content": f"ENGLISH SOURCE:\n{source}\n\nHINDI TRANSLATION:\n{translated}"},
        ],
        response_format={"json_schema": {"schema": JUDGE_SCHEMA}},
        temperature=0,
        timeout=90.0,
    )
    payload = json.loads(response.choices[0].message.content)
    verdict = payload.get("verdict")
    issues = payload.get("issues")
    corrected = payload.get("corrected_translation", "").strip()
    if verdict not in {"pass", "revise"} or not isinstance(issues, list):
        raise ValueError("Translation judge returned an invalid verdict")
    if verdict == "revise":
        if not corrected:
            raise ValueError("Translation judge requested revision without a correction")
        return corrected, [str(issue) for issue in issues]
    return translated, []
TOKEN_RE = re.compile(
    r"\d+(?:[.,/:]\d+)*(?:\s?(?:mg|mcg|g|kg|ml|mL|l|units?|%|"
    r"milligrams?|micrograms?|grams?|kilograms?|millilit(?:er|re)s?|"
    r"lit(?:er|re)s?|tablets?|capsules?))?",
    re.I,
)
MONTH_RE = re.compile(
    r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|"
    r"Dec(?:ember)?)\b",
    re.I,
)


def _protected_tokens(source: str, facts: list[Fact]) -> set[str]:
    tokens = set(TOKEN_RE.findall(source))
    tokens.update(MONTH_RE.findall(source))
    for fact in facts:
        if fact.kind == "medication":
            # Keep medication names in their source spelling. This deliberately
            # errs toward review when the source uses unfamiliar brand names.
            for token in re.findall(r"\b[A-Za-z][A-Za-z0-9-]*\b", fact.text_en):
                if token.casefold() not in {"take", "tablet", "tablets", "daily", "for", "days", "mg", "by", "mouth"}:
                    tokens.add(token)
    return tokens


def _back_translate(text: str) -> str:
    response = chat_completion(
        model=settings.translation_model_id,
        messages=[
            {"role": "system", "content": (
                "Translate the supplied Hindi discharge explanation into plain English. "
                "Translate only; do not explain, summarize, or add instructions. "
                "Return only the English translation."
            )},
            {"role": "user", "content": text},
        ],
        temperature=0,
        timeout=60.0,
    )
    result = response.choices[0].message.content
    if not result or not result.strip():
        raise ValueError("Back-translation returned empty text")
    return result.strip()


def translate_claims(claims: list[Claim], facts: list[Fact], lang: str) -> list[Claim]:
    if lang == "en":
        return claims
    language = LANGUAGES.get(lang)
    if language is None:
        raise ValueError(f"Unsupported language: {lang}")
    facts_by_id = {fact.id: fact for fact in facts}
    for claim in claims:
        linked_facts = [facts_by_id[fact_id] for fact_id in claim.fact_ids if fact_id in facts_by_id]
        protected = _protected_tokens(claim.text, linked_facts)
        try:
            response = chat_completion(
                model=settings.translation_model_id,
                messages=[
                    {"role": "system", "content": (
                        f"Translate the supplied discharge explanation into plain {language}. "
                        "Translate only; do not explain, summarize, or add instructions. "
                        "Preserve every medication name, number, date, dose, unit, and frequency "
                        "exactly as written. Return only the translation."
                    )},
                    {"role": "user", "content": claim.text},
                ],
                temperature=0,
                timeout=60.0,
            )
            translated = response.choices[0].message.content
            if not translated or not translated.strip():
                raise ValueError("Translation returned empty text")
            translated = translated.strip()
            try:
                reviewed_translation, judge_issues = _judge_translation(claim.text, translated)
                corrected_missing = [token for token in protected if token.casefold() not in reviewed_translation.casefold()]
                if not corrected_missing:
                    translated = reviewed_translation
                    claim.checks["translation_judge"] = "corrected" if judge_issues else "passed"
                else:
                    claim.checks["translation_judge"] = "flagged"
                    claim.reason_codes.append("translation_judge_dropped_protected_detail")
            except Exception:
                claim.checks["translation_judge"] = "not_run"
                claim.reason_codes.append("translation_judge_not_run")
            missing = [token for token in protected if token.casefold() not in translated.casefold()]
            claim.source_language_text = claim.text
            claim.text = translated
            claim.language = lang
            # The detailed deterministic checks were run on the English draft.
            # Do not present them as if they verified the translated wording.
            for check_name in (
                "exact_match", "risk_rules", "ambiguous_medication_details",
                "medication_names", "high_alert_medication", "unsupported_details",
                "numeric_details", "instruction_polarity", "medication_contradictions",
                "entailment_judge",
            ):
                if check_name in claim.checks:
                    claim.checks[check_name] = "not_run"
            claim.check_details = {}
            try:
                round_trip = _back_translate(translated)
                back_status, back_reasons = check_claim_entailment(
                    round_trip, [claim.source_language_text],
                    enabled=settings.entailment_judge_enabled,
                )
                claim.checks["back_translation"] = back_status
                claim.reason_codes.extend(back_reasons)
            except Exception:
                claim.checks["back_translation"] = "not_run"
            if missing:
                claim.checks["translation"] = "failed"
                claim.reason_codes.append("translation_protected_detail_missing")
            else:
                claim.checks["translation"] = "review_suggested"
                claim.reason_codes.append("translation_requires_human_review")
            # A model round trip is only a screening signal. Keep a qualified
            # human review for every translated claim.
            claim.review_priority_score = max(claim.review_priority_score if claim.review_priority_score is not None else 0.0, 0.51)
            claim.state = State.NEEDS_CLINICIAN
        except Exception:
            claim.language = "en"
            claim.review_priority_score = 1.0
            claim.state = State.NEEDS_CLINICIAN
            claim.checks["translation"] = "not_run"
            claim.checks["back_translation"] = "not_run"
            claim.reason_codes.append("translation_failed")
    return claims
