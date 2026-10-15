"""Source-grounded claim checks and conservative review routing."""

import logging
import re

from ..config import settings
from ..models import Claim, Fact, Sentence, State, VerificationCheck
from ..rules.risk_rules import find_high_alert_medications, find_known_medication_entities
from .extract import SECTION_KIND_MAP, _normalize_section
from .entailment import check_claim_entailment
from .verify_details import (
    check_instruction_polarity,
    check_clause_preservation,
    check_synonym_drift,
    check_unsupported_attributions,
    check_unsupported_numeric_details,
    check_warning_sign_urgency,
    check_unsupported_medication_context,
)
from .verify_medications import (
    check_ambiguous_medication_details,
    check_medication_consistency,
    check_unsupported_medication_names,
    extract_doses,
    extract_durations,
    extract_frequencies,
    extract_timings,
    find_conflicting_medication_fact_ids,
)

logger = logging.getLogger(__name__)


def _has_medication_to_verify(facts: list[Fact]) -> bool:
    """Require a named medicine or a concrete generic medication instruction."""
    for fact in facts:
        if fact.kind != "medication":
            continue
        source = fact.text_en
        if find_known_medication_entities(source):
            return True
        if any((extract_doses(source), extract_frequencies(source), extract_durations(source), extract_timings(source))) or re.search(
            r"\b(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
            r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty)\s+"
            r"(?:times?\s+(?:a|per)\s+week|days?\s+(?:a|per)\s+week)\b",
            source,
            re.I,
        ):
            return True
        if re.search(r"\b(?:medications?|medicines?|drugs?|tablets?|capsules?)\b", source, re.I) and re.search(
            r"\b(?:as directed|as prescribed|prescription label|dose|dosage)\b", source, re.I
        ):
            return True
    return False


REASON_MESSAGES = {
    "invalid_or_missing_source": "A source reference is missing, invalid, or inconsistent with the linked facts, so this claim cannot be traced reliably to the document.",
    "invalid_or_missing_fact": "One or more referenced facts do not exist, so the explanation could not be compared against them.",
    "medication_dose_mismatch": "The generated explanation states a different medication dose from the linked source instruction.",
    "medication_frequency_mismatch": "The generated explanation states a different medication frequency from the linked source instruction.",
    "as_needed_duration_added": "The source says to take this medicine as needed. The explanation changes that to 'as long as needed,' which can read like a duration. Preserve the as-needed wording.",
    "medication_frequency_requires_clinician_review": "The medication frequency exceeds the prototype's configured review threshold. A clinician must assess the original instruction; no replacement schedule has been inferred.",
    "medication_duration_mismatch": "The generated explanation states a different treatment duration from the linked source instruction.",
    "medication_timing_mismatch": "The generated explanation changes when the medication should be taken, such as morning, evening, or with food.",
    "unsupported_medication_frequency": "The source does not establish the frequency stated in the generated medication explanation.",
    "medication_attribute_unrecognized": "Medication schedule details could not be interpreted reliably, so this comparison is incomplete.",
    "ambiguous_medication_schedule": "The source medication wording does not establish a clear schedule. A clinician must clarify the intended instruction.",
    "interpreted_ambiguous_medication_schedule": "The generated explanation turns an ambiguous source schedule into a definite frequency or duration that the source does not establish.",
    "ambiguous_medication_details": "The source medication wording does not contain a schedule the verifier can confidently identify. This is uncertainty, not confirmation that the generated instruction is correct.",
    "unsupported_attribution": "The generated explanation attributes an instruction to a clinician, but the linked source does not make that attribution.",
    "unsupported_numeric_detail": "The generated explanation contains a number or date that is absent from the linked source facts.",
    "source_clause_omitted": "The source includes an exception or condition clause that the explanation does not preserve.",
    "clinical_synonym_drift": "The explanation replaces source wording with a phrase that changes the stated clinical condition or certainty.",
    "unsupported_medication_name": "A recognized medication name in the generated explanation is absent from the linked medication facts.",
    "unsupported_medication_context": "The explanation adds a medication class or purpose that the source does not state. This may be true in general, but it is not source-grounded.",
    "medication_name_unrecognized": "The medication-name check could not match a name in the explanation to its limited configured name list. The system has not inferred or corrected the name; verify it against the source.",
    "instruction_polarity_mismatch": "The generated explanation changes the source's negation or stop/continue instruction.",
    "contradictory_medication_instructions": "The linked source facts contain conflicting medication directions.",
    "unsupported_claim_detail": "The claim support check identified a detail that the linked source facts do not support.",
    "warning_sign_escalation_softened": "The explanation lowers the response level from urgent medical care to contacting a doctor or clinic. Preserve the source's urgent escalation instruction.",
    "unsupported_details_check_incomplete": "The deterministic rules checked specific details, but the broader source-support judge is not configured. This check cannot establish that every other claim detail is supported.",
    "uncertain_claim_entailment": "The claim support check could not determine whether the linked source facts support this wording.",
    "entailment_judge_failed": "The claim support check did not complete, so it could not assess source support.",
    "high_alert_medication_review": "A medication matched the configured high-alert list and requires clinician review.",
    "verification_layers_not_fully_configured": "The verification results above name each layer that is not configured or did not run. This claim remains in review.",
    "human_review_recommended": "Configured checks found no specific discrepancy. This prototype leaves claims in human review because passing checks do not establish clinical correctness.",
    "llm_generation_failed": "Explanation generation failed. The source text is shown for review; the generated explanation must not be relied on.",
    "llm_generation_not_configured": "Explanation generation is not configured, so a source-linked explanation was not produced.",
    "translation_not_configured": "Translation verification is not configured and was not performed.",
    "human_edit_requires_reverification": "A reviewer edited this explanation. The edited wording has not yet been re-verified against its sources.",
    "translation_protected_detail_missing": "A medication name, number, dose, unit, or date did not remain verbatim in the translation.",
    "translation_requires_human_review": "Critical tokens were preserved, but translation meaning has not been independently validated. Human review is required.",
    "translation_failed": "Local translation failed. The English claim is retained and marked for human review.",
    "ocr_source_requires_review": "Local OCR produced the source text. Review the recognized text against the scanned page before relying on any explanation.",
}


CHECK_REASONS = {
    "source_ids": ["invalid_or_missing_source", "invalid_or_missing_fact"],
    "risk_rules": [
        "interpreted_ambiguous_medication_schedule", "unsupported_medication_frequency",
        "medication_dose_mismatch", "medication_frequency_mismatch",
        "medication_frequency_requires_clinician_review",
        "as_needed_duration_added",
        "medication_duration_mismatch", "medication_timing_mismatch",
        "ambiguous_medication_schedule", "medication_attribute_unrecognized",
    ],
    "ambiguous_medication_details": ["ambiguous_medication_details"],
    "medication_names": ["unsupported_medication_name", "medication_name_unrecognized"],
    "unsupported_details": [
        "unsupported_attribution", "unsupported_claim_detail", "unsupported_medication_context",
        "unsupported_medication_frequency", "interpreted_ambiguous_medication_schedule",
        "uncertain_claim_entailment", "unsupported_details_check_incomplete",
    ],
    "medication_context": ["unsupported_medication_context"],
    "high_alert_medication": ["high_alert_medication_review"],
    "numeric_details": ["unsupported_numeric_detail"],
    "clause_preservation": ["source_clause_omitted"],
    "synonym_drift": ["clinical_synonym_drift"],
    "instruction_polarity": ["instruction_polarity_mismatch"],
    "medication_contradictions": ["contradictory_medication_instructions"],
    "entailment_judge": ["uncertain_claim_entailment", "entailment_judge_failed", "unsupported_claim_detail"],
    "warning_sign_urgency": ["warning_sign_escalation_softened"],
    "back_translation": [],
}


def normalize(text: str) -> str:
    """Normalize text for case-insensitive comparisons."""
    return " ".join(text.casefold().split()).strip()


def normalize_for_source_match(text: str) -> str:
    """Ignore a simple list label added by the explanation formatter."""
    text = re.sub(r"^\s*(?:[a-z]|\d{1,3})[.)]\s+", "", text, count=1, flags=re.I)
    return normalize(text)


def normalize_known_paraphrases(text: str) -> str:
    """Canonicalize a small set of common, source-preserving wording pairs."""
    normalized = normalize(text)
    normalized = re.sub(r"\bmedicines?\b", "medication", normalized)
    normalized = re.sub(r"\bprescribed for you\b", "prescribed to you", normalized)
    normalized = re.sub(
        r"\b(?:once\s+(?:a|per)\s+day|one time\s+(?:a|per)\s+day|once\s+daily|every day|daily)\b",
        "once daily",
        normalized,
    )
    return normalized


def _status_message(status: str) -> str:
    return {
        "passed": "This check ran and found no issue in the information it evaluates. This result alone does not establish clinical correctness.",
        "failed": "This check ran and found a discrepancy that needs review.",
        "review_suggested": "This check ran but found uncertainty it could not resolve.",
        "not_run": "This check did not run, so it provides no evidence that the explanation is supported.",
        "not_configured": "This check is not configured and was not performed.",
        "not_applicable": "This check does not apply to this claim type.",
        "informational": "The wording differs from the source; review the difference before relying on the explanation.",
        "failed_or_not_exact": "The wording differs from the source. A wording difference alone does not establish a change in meaning.",
    }.get(status, "The check returned an unrecognized status.")


def _build_check_details(claim: Claim, source_text: str | None) -> None:
    claim.check_details = {}
    for name, status in claim.checks.items():
        reason_code = next(
            (code for code in CHECK_REASONS.get(name, []) if code in claim.reason_codes),
            None,
        )
        claim.check_details[name] = VerificationCheck(
            name=name,
            status=status,
            reason_code=reason_code,
            message=(
                "The wording matches the source exactly. Text equality does not establish that a medication instruction is safe."
                if name == "exact_match" and status == "passed"
                else "The entailment judge is not configured, so semantic support was not assessed."
                if name == "entailment_judge" and status == "not_configured"
                else "The entailment judge did not complete, so semantic support could not be assessed."
                if name == "entailment_judge" and status == "not_run"
                else "The back-translation check did not complete, so translated meaning was not assessed."
                if name == "back_translation" and status == "not_run"
                else REASON_MESSAGES.get(reason_code, _status_message(status))
            ),
            source_text=source_text,
            claim_text=claim.text,
            performed=status not in {"not_run", "not_configured", "not_applicable"},
        )


def verify_claims(
    claims: list[Claim],
    sentences: list[Sentence],
    facts: list[Fact],
) -> list[Claim]:
    """Run deterministic source checks and route uncertainty conservatively.

    The prototype does not mark claims VERIFIED: optional and required
    verification layers are not yet all configured.
    """
    sentences_by_id = {sentence.id: sentence for sentence in sentences}
    facts_by_id = {fact.id: fact for fact in facts}
    conflicting_fact_ids = find_conflicting_medication_fact_ids(facts)
    managed_reasons = set(REASON_MESSAGES)
    critical_reasons = {
        "invalid_or_missing_source", "invalid_or_missing_fact",
        "medication_dose_mismatch", "medication_frequency_mismatch",
        "medication_frequency_requires_clinician_review",
        "medication_duration_mismatch", "medication_timing_mismatch",
        "unsupported_medication_frequency", "as_needed_duration_added", "interpreted_ambiguous_medication_schedule",
        "unsupported_attribution", "unsupported_numeric_detail",
        "source_clause_omitted", "clinical_synonym_drift",
        "unsupported_medication_name", "instruction_polarity_mismatch",
        "contradictory_medication_instructions", "warning_sign_escalation_softened",
        "llm_generation_failed",
        "llm_generation_not_configured",
        "translation_protected_detail_missing", "translation_failed",
        "ocr_source_requires_review",
    }

    for claim in claims:
        persistent_reasons = {
            "llm_generation_failed", "llm_generation_not_configured",
            "human_edit_requires_reverification", "human_rejected",
            "translation_not_configured",
            "ocr_source_requires_review",
        }
        claim.reason_codes = [
            reason for reason in claim.reason_codes
            if isinstance(reason, str) and reason.strip() and reason.strip() != "-"
            and (reason not in managed_reasons or reason in persistent_reasons)
        ]
        source_ids_valid = bool(claim.source_ids) and all(
            source_id in sentences_by_id for source_id in claim.source_ids
        )
        fact_ids_valid = bool(claim.fact_ids) and all(
            fact_id in facts_by_id for fact_id in claim.fact_ids
        )
        linked_facts = [facts_by_id[fact_id] for fact_id in claim.fact_ids if fact_id in facts_by_id]
        fact_sources_valid = all(
            fact.source_ids
            and all(
                source_id in sentences_by_id
                and fact.text_en.strip() == sentences_by_id[source_id].text.strip()
                and (
                    SECTION_KIND_MAP.get(_normalize_section(sentences_by_id[source_id].section))
                    in {None, fact.kind}
                )
                for source_id in fact.source_ids
            )
            for fact in linked_facts
        )
        cited_sources = {source_id for fact in linked_facts for source_id in fact.source_ids}
        citation_consistent = bool(linked_facts) and cited_sources == set(claim.source_ids)
        sources_valid = source_ids_valid and fact_ids_valid and fact_sources_valid and citation_consistent
        claim.checks = {}
        claim.checks["source_ids"] = "passed" if sources_valid else "failed"
        claim.checks["fact_extraction"] = "passed" if sources_valid else "failed"
        if not source_ids_valid or not fact_sources_valid or not citation_consistent:
            claim.reason_codes.append("invalid_or_missing_source")
        if not fact_ids_valid:
            claim.reason_codes.append("invalid_or_missing_fact")

        if sources_valid:
            candidates = [sentences_by_id[source_id].text for source_id in claim.source_ids]
            candidates.extend(fact.text_en for fact in linked_facts)
            exact_match = any(
                normalize_for_source_match(claim.text) == normalize_for_source_match(value)
                for value in candidates
            )
        else:
            exact_match = False
        claim.checks["exact_match"] = (
            ("passed" if exact_match else "informational")
            if sources_valid else "not_run"
        )
        known_paraphrase_match = bool(
            sources_valid
            and not exact_match
            and any(
                normalize_known_paraphrases(normalize_for_source_match(claim.text))
                == normalize_known_paraphrases(normalize_for_source_match(value))
                for value in candidates
            )
        )

        has_medication_mention = _has_medication_to_verify(linked_facts)
        medication_check_status = "not_applicable" if sources_valid and not has_medication_mention else "not_run"
        risk_status, risk_problems = (
            check_medication_consistency(claim, linked_facts)
            if sources_valid and has_medication_mention
            else (medication_check_status, [])
        )
        claim.checks["risk_rules"] = risk_status
        claim.reason_codes.extend(risk_problems)
        ambiguous_status, ambiguous_problems = (
            check_ambiguous_medication_details(linked_facts)
            if sources_valid and has_medication_mention
            else (medication_check_status, [])
        )
        claim.checks["ambiguous_medication_details"] = ambiguous_status
        claim.reason_codes.extend(ambiguous_problems)
        medication_name_status, medication_name_problems = (
            check_unsupported_medication_names(claim, linked_facts)
            if sources_valid and has_medication_mention
            else (medication_check_status, [])
        )
        claim.checks["medication_names"] = medication_name_status
        claim.reason_codes.extend(medication_name_problems)

        medication_context_status, medication_context_problems = (
            check_unsupported_medication_context(claim, linked_facts)
            if sources_valid and has_medication_mention
            else (medication_check_status, [])
        )
        claim.checks["medication_context"] = medication_context_status
        claim.reason_codes.extend(medication_context_problems)

        high_alert_names = (
            find_high_alert_medications(" ".join(fact.text_en for fact in linked_facts))
            if sources_valid else []
        )
        claim.checks["high_alert_medication"] = (
            "not_run" if not sources_valid
            else "review_suggested" if high_alert_names
            else "passed" if has_medication_mention
            else "not_applicable"
        )
        if high_alert_names:
            claim.reason_codes.append("high_alert_medication_review")

        entailment_status, entailment_problems = (
            ("passed", []) if sources_valid and exact_match else
            ("not_applicable", []) if known_paraphrase_match else check_claim_entailment(
                claim.text, [fact.text_en for fact in linked_facts],
                enabled=settings.entailment_judge_enabled,
            ) if sources_valid else ("not_run", [])
        )
        # A single local model verdict is a screening signal, not enough to
        # label a paraphrase definitively unsupported. Keep it as uncertainty.
        if entailment_status == "failed" and "unsupported_claim_detail" in entailment_problems:
            entailment_status, entailment_problems = "review_suggested", ["uncertain_claim_entailment"]
        claim.checks["entailment_judge"] = entailment_status
        claim.reason_codes.extend(entailment_problems)

        unsupported_status, unsupported_problems = (
            check_unsupported_attributions(claim, linked_facts) if sources_valid else ("not_run", [])
        )
        unsupported_medication_problems = [
            code for code in risk_problems
            if code in {"unsupported_medication_frequency", "interpreted_ambiguous_medication_schedule"}
        ]
        unsupported_problems.extend(unsupported_medication_problems)
        unsupported_problems.extend(medication_context_problems)
        if unsupported_medication_problems:
            unsupported_status = "failed"
        elif medication_context_problems:
            unsupported_status = "failed"
        elif "unsupported_claim_detail" in entailment_problems:
            unsupported_status = "failed"
            unsupported_problems.append("unsupported_claim_detail")
        elif unsupported_status != "failed" and "uncertain_claim_entailment" in entailment_problems:
            unsupported_status = "review_suggested"
            unsupported_problems.append("uncertain_claim_entailment")
        elif unsupported_status != "failed" and entailment_status in {"not_run", "not_configured"} and sources_valid:
            unsupported_status = "review_suggested"
            unsupported_problems.append("unsupported_details_check_incomplete")
        claim.checks["unsupported_details"] = unsupported_status
        claim.reason_codes.extend(unsupported_problems)

        numeric_status, numeric_problems = (
            check_unsupported_numeric_details(claim, linked_facts) if sources_valid else ("not_run", [])
        )
        claim.checks["numeric_details"] = numeric_status
        claim.reason_codes.extend(numeric_problems)
        polarity_status, polarity_problems = (
            check_instruction_polarity(claim, linked_facts) if sources_valid else ("not_run", [])
        )
        claim.checks["instruction_polarity"] = polarity_status
        claim.reason_codes.extend(polarity_problems)
        clause_status, clause_problems = (
            check_clause_preservation(claim, linked_facts) if sources_valid else ("not_run", [])
        )
        claim.checks["clause_preservation"] = clause_status
        claim.reason_codes.extend(clause_problems)
        synonym_status, synonym_problems = (
            check_synonym_drift(claim, linked_facts) if sources_valid else ("not_run", [])
        )
        claim.checks["synonym_drift"] = synonym_status
        claim.reason_codes.extend(synonym_problems)
        urgency_status, urgency_problems = (
            check_warning_sign_urgency(claim, linked_facts) if sources_valid else ("not_run", [])
        )
        claim.checks["warning_sign_urgency"] = urgency_status
        claim.reason_codes.extend(urgency_problems)

        has_conflicts = sources_valid and bool(
            conflicting_fact_ids.intersection(fact.id for fact in linked_facts)
        )
        claim.checks["medication_contradictions"] = (
            ("failed" if has_conflicts else "passed")
            if sources_valid and has_medication_mention
            else "not_applicable" if sources_valid
            else "not_run"
        )
        conflict_problems = ["contradictory_medication_instructions"] if has_conflicts else []
        claim.reason_codes.extend(conflict_problems)
        # Back-translation only applies after a claim is translated.
        claim.checks["back_translation"] = "not_applicable"
        # Translation token checks only apply to non-English output.
        claim.checks["translation"] = "not_applicable"

        # Weighted ordering heuristic: higher values reflect stronger review
        # signals. It remains an ordering aid, not a probability of correctness.
        # A small baseline keeps routine human review distinguishable from a
        # high-risk discrepancy; literal paraphrases add review effort only.
        priority = 0.9 if not sources_valid else 0.06
        if claim.checks.get("exact_match") == "informational":
            priority = max(priority, 0.14)
        check_weights = {
            "risk_rules": (0.72, 0.42, 0.24),
            "medication_names": (0.72, 0.42, 0.24),
            "numeric_details": (0.72, 0.42, 0.24),
            "instruction_polarity": (0.82, 0.48, 0.24),
            "medication_contradictions": (0.9, 0.5, 0.24),
            "unsupported_details": (0.82, 0.18, 0.28),
            "entailment_judge": (0.82, 0.18, 0.28),
            "warning_sign_urgency": (0.9, 0.5, 0.24),
        }
        for name, (failed, uncertain, incomplete) in check_weights.items():
            status = claim.checks.get(name)
            weight = {
                "failed": failed,
                "review_suggested": uncertain,
                "not_run": incomplete,
                "not_configured": incomplete,
            }.get(status, 0.0)
            priority = 1 - (1 - priority) * (1 - weight)
        if any(code in claim.reason_codes for code in critical_reasons):
            priority = max(priority, 0.9)
        claim.review_priority_score = round(min(1.0, priority), 2)

        generation_failed = any(
            code in claim.reason_codes
            for code in {"llm_generation_failed", "llm_generation_not_configured"}
        )
        claim.reason_codes = list(dict.fromkeys(claim.reason_codes))
        verification_incomplete = any(
            claim.checks.get(name) in {"not_run", "not_configured"}
            for name in ("entailment_judge", "back_translation")
        )
        if verification_incomplete:
            claim.reason_codes.append("verification_layers_not_fully_configured")
        deterministic_failure = any(
            status == "failed"
            for name, status in claim.checks.items()
            if name != "entailment_judge"
        )
        requires_clinician = (
            generation_failed
            or not sources_valid
            or deterministic_failure
            or bool(set(claim.reason_codes).intersection(critical_reasons))
            or "ambiguous_medication_schedule" in claim.reason_codes
        )
        if requires_clinician:
            claim.state = State.NEEDS_CLINICIAN
        elif (exact_match or known_paraphrase_match) and not claim.reason_codes:
            claim.state = State.SOURCE_SUPPORTED
        else:
            claim.state = State.REVIEW_SUGGESTED
            if not claim.reason_codes:
                claim.reason_codes.append("human_review_recommended")
        claim.reason_codes = list(dict.fromkeys(claim.reason_codes))
        source_text = " ".join(
            sentences_by_id[source_id].text
            for source_id in claim.source_ids if source_id in sentences_by_id
        ) or None
        _build_check_details(claim, source_text)
        logger.info(
            "Claim verification completed claim_id=%s state=%s reason_codes=%s",
            claim.id,
            claim.state.value,
            claim.reason_codes,
        )

    return claims
