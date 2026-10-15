"""Local-model translation with source-linked conservative review handling."""

from __future__ import annotations

import re
import json
import time

from ..config import settings
from ..llm_client import chat_completion, text_completion
from ..models import Claim, Fact, State
from .entailment import check_claim_entailment

SARVAM_TRANSLATION_MODEL = "mashriram/sarvam-1"
LANGUAGES = {
    "en": "English",
    "hi": "Hindi",
    "bn": "Bengali",
    "gu": "Gujarati",
    "kn": "Kannada",
    "ml": "Malayalam",
    "mr": "Marathi",
    "or": "Odia",
    "pa": "Punjabi",
    "ta": "Tamil",
    "te": "Telugu",
}
TRANSLATION_EXAMPLES = {
    "hi": "आज मौसम अच्छा है।",
    "bn": "আজ আবহাওয়া সুন্দর।",
    "gu": "આજે હવામાન સારું છે.",
    "kn": "ಇಂದು ಹವಾಮಾನ ಚೆನ್ನಾಗಿದೆ.",
    "ml": "ഇന്ന് കാലാവസ്ഥ നല്ലതാണ്.",
    "mr": "आज हवामान छान आहे.",
    "or": "ଆଜି ପାଗ ଭଲ ଅଛି।",
    "pa": "ਅੱਜ ਮੌਸਮ ਚੰਗਾ ਹੈ।",
    "ta": "இன்று வானிலை நன்றாக உள்ளது.",
    "te": "ఈరోజు వాతావరణం బాగుంది.",
}
LANGUAGE_SCRIPT_RANGES = {
    "hi": (0x0900, 0x097F),
    "mr": (0x0900, 0x097F),
    "bn": (0x0980, 0x09FF),
    "pa": (0x0A00, 0x0A7F),
    "gu": (0x0A80, 0x0AFF),
    "or": (0x0B00, 0x0B7F),
    "ta": (0x0B80, 0x0BFF),
    "te": (0x0C00, 0x0C7F),
    "kn": (0x0C80, 0x0CFF),
    "ml": (0x0D00, 0x0D7F),
}
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


def _judge_translation(source: str, translated: str, language: str) -> tuple[str, list[str], str]:
    language_name = LANGUAGES[language]
    response = chat_completion(
        model=settings.translation_judge_model_id,
        messages=[
            {"role": "system", "content": (
                f"Review a {language_name} translation of an English hospital discharge instruction. "
                f"Check that every meaning is preserved, nothing is omitted or added, and the {language_name} is clear and natural. "
                "Pay special attention to negation, medication instructions, timing, warnings, and follow-up. "
                f"If there is any issue, return verdict revise and provide a complete corrected {language_name} translation. "
                "Do not invent facts. If the translation is accurate, return pass and an empty corrected_translation. "
                "This is a conservative screening check, not clinical approval."
            )},
            {"role": "user", "content": f"ENGLISH SOURCE:\n{source}\n\n{language_name.upper()} TRANSLATION:\n{translated}"},
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
        return verdict, [str(issue) for issue in issues], corrected
    return verdict, [], ""


def _translate_text(
    source: str,
    language: str,
    *,
    review_issues: list[str] | None = None,
    suggestion: str = "",
) -> str:
    language_name = LANGUAGES[language]
    feedback = ""
    if review_issues:
        feedback = "Reviewer notes to fix: " + "; ".join(review_issues) + "\n"
        if suggestion:
            feedback += f"Reviewer suggestion for reference only: {suggestion}\n"
    prompt = (
        f"Task: Translate English into {language_name}. Preserve all names, numbers, dates, doses, units, "
        "frequencies, negation, warnings, and conditions. Return only the translation, without a label.\n\n"
        f"English: The weather is nice today.\n{language_name}: {TRANSLATION_EXAMPLES[language]}\n\n"
        f"{feedback}English: {source}\n{language_name}:"
    )
    result = text_completion(
        model=SARVAM_TRANSLATION_MODEL,
        prompt=prompt,
        temperature=0,
        timeout=60.0,
    )
    if not result or not result.strip():
        raise ValueError("Translation returned empty text")
    translated = result.strip()
    label = f"{language_name}:"
    if translated.casefold().startswith(label.casefold()):
        translated = translated[len(label):].strip()
    # Some raw-completion responses append in-context examples after the
    # translation. Keep the answer and drop any echoed English example block.
    translated = re.split(r"\n\s*English\s*:", translated, maxsplit=1, flags=re.IGNORECASE)[0].strip()
    translated = re.sub(r"\s*</s>\s*$", "", translated).strip()
    start, end = LANGUAGE_SCRIPT_RANGES[language]
    if not any(start <= ord(character) <= end for character in translated):
        raise ValueError(f"Sarvam-1 returned no {language_name} script text")
    return translated


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


def _back_translate(text: str, language: str) -> str:
    language_name = LANGUAGES[language]
    result = text_completion(
        model=SARVAM_TRANSLATION_MODEL,
        prompt=(
            f"Task: Translate {language_name} into English. Return only the English translation, without a label.\n\n"
            f"{language_name}: {TRANSLATION_EXAMPLES[language]}\nEnglish: The weather is nice today.\n\n"
            f"{language_name}: {text}\nEnglish:"
        ),
        temperature=0,
        timeout=60.0,
    )
    if not result or not result.strip():
        raise ValueError("Back-translation returned empty text")
    return result.strip()


def translate_claims(claims: list[Claim], facts: list[Fact], lang: str) -> list[Claim]:
    if lang == "en":
        return claims
    language_name = LANGUAGES.get(lang)
    if language_name is None:
        raise ValueError(f"Unsupported language: {lang}")
    total = len(claims)
    started_at = time.perf_counter()
    print(f"[translation] Starting {language_name} translation for {total} claims with {SARVAM_TRANSLATION_MODEL}.", flush=True)
    facts_by_id = {fact.id: fact for fact in facts}
    for index, claim in enumerate(claims, start=1):
        claim_started_at = time.perf_counter()
        print(f"[translation] Claim {index}/{total}: translating with Sarvam-1.", flush=True)
        linked_facts = [facts_by_id[fact_id] for fact_id in claim.fact_ids if fact_id in facts_by_id]
        protected = _protected_tokens(claim.text, linked_facts)
        try:
            translated = _translate_text(claim.text, lang)
            try:
                print(f"[translation] Claim {index}/{total}: checking translation with the local reviewer.", flush=True)
                verdict, judge_issues, suggestion = _judge_translation(claim.text, translated, lang)
                if verdict == "revise":
                    # Keep Sarvam-1 as the producer of user-facing translations,
                    # including any revision prompted by the reviewer.
                    print(f"[translation] Claim {index}/{total}: applying reviewer feedback with Sarvam-1.", flush=True)
                    translated = _translate_text(
                        claim.text, lang, review_issues=judge_issues, suggestion=suggestion
                    )
                    corrected_missing = [token for token in protected if token.casefold() not in translated.casefold()]
                    if not corrected_missing:
                        claim.checks["translation_judge"] = "corrected"
                    else:
                        claim.checks["translation_judge"] = "flagged"
                        claim.reason_codes.append("translation_judge_dropped_protected_detail")
                else:
                    claim.checks["translation_judge"] = "passed"
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
                round_trip = _back_translate(translated, lang)
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
            print(
                f"[translation] Claim {index}/{total}: complete in {time.perf_counter() - claim_started_at:.1f}s "
                f"({time.perf_counter() - started_at:.1f}s total).",
                flush=True,
            )
        except Exception:
            print(
                f"[translation] Claim {index}/{total}: failed after {time.perf_counter() - claim_started_at:.1f}s; "
                "keeping the English text for review.",
                flush=True,
            )
            claim.language = "en"
            claim.review_priority_score = 1.0
            claim.state = State.NEEDS_CLINICIAN
            claim.checks["translation"] = "not_run"
            claim.checks["back_translation"] = "not_run"
            claim.reason_codes.append("translation_failed")
    print(f"[translation] Finished {language_name} translation for {total} claims in {time.perf_counter() - started_at:.1f}s.", flush=True)
    return claims
