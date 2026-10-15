from ..models import Claim, Fact, State


def combine_states(states: list[State]) -> State:
    """Return the most conservative state from a list of states."""
    order = {
        State.VERIFIED: 0,
        State.SOURCE_SUPPORTED: 1,
        State.REVIEW_SUGGESTED: 2,
        State.NEEDS_CLINICIAN: 3,
    }

    return (
        max(
            states,
            key=lambda state: order[state],
        )
        if states
        else State.NEEDS_CLINICIAN
    )


def build_doctor_questions(
    facts: list[Fact],
    claims: list[Claim],
) -> list[str]:
    questions: list[str] = []
    facts_by_id = {fact.id: fact for fact in facts}
    for claim in claims:
        reasons = set(claim.reason_codes)
        source_text = " ".join(
            facts_by_id[fact_id].text_en
            for fact_id in claim.fact_ids if fact_id in facts_by_id
        )
        if "ambiguous_medication_schedule" in reasons or "interpreted_ambiguous_medication_schedule" in reasons:
            questions.append(
                "The source medication instruction is ambiguous: ‘"
                + source_text
                + "’ What schedule should the patient follow? Please clarify the intended instruction without assuming the generated schedule is correct."
            )
            continue
        if "medication_frequency_requires_clinician_review" in reasons:
            questions.append(
                "The source medication instruction says ‘" + source_text
                + "’ and triggered the configured frequency safety review. Is this instruction intentional and safe to communicate? Do not infer a different schedule."
            )
            continue
        if "medication_frequency_mismatch" in reasons or "unsupported_medication_frequency" in reasons:
            questions.append(
                "The source medication instruction says ‘"
                + source_text
                + "’, while the generated explanation says ‘"
                + claim.text
                + "’. Which frequency should be communicated?"
            )
            continue
        if "as_needed_duration_added" in reasons:
            questions.append(
                "The source says ‘" + source_text + "’, while the explanation says ‘"
                + claim.text + "’. Should the medicine be taken only when needed for the stated symptom?"
            )
            continue
        if "warning_sign_escalation_softened" in reasons:
            questions.append(
                "The source says ‘" + source_text + "’, while the explanation says ‘"
                + claim.text + "’. Should the urgent medical care instruction be restored?"
            )
            continue
        targeted_reasons = {
            "ambiguous_medication_schedule", "interpreted_ambiguous_medication_schedule",
            "medication_frequency_mismatch", "unsupported_medication_frequency",
            "medication_frequency_requires_clinician_review", "medication_dose_mismatch",
            "medication_duration_mismatch", "medication_timing_mismatch",
            "unsupported_numeric_detail", "unsupported_attribution",
            "unsupported_medication_name", "instruction_polarity_mismatch",
            "contradictory_medication_instructions", "high_alert_medication_review",
            "warning_sign_escalation_softened",
            "medication_attribute_unrecognized", "medication_name_unrecognized",
        }
        if not reasons.intersection(targeted_reasons):
            continue
        if "medication_dose_mismatch" in reasons or "medication_duration_mismatch" in reasons or "medication_timing_mismatch" in reasons:
            questions.append(
                "Please compare the medication source instruction ‘"
                + source_text
                + "’ with the generated explanation ‘"
                + claim.text
                + "’ and clarify the dose, duration, or timing that should be communicated."
            )
            continue
        if "medication_attribute_unrecognized" in reasons or "medication_name_unrecognized" in reasons:
            questions.append(
                "The system could not reliably interpret or identify part of this medication instruction: ‘"
                + source_text
                + "’. Please clarify the source wording or medication identity without assuming a typical schedule or correcting the name."
            )
            continue
        if "unsupported_claim_detail" in reasons or "unsupported_numeric_detail" in reasons or "unsupported_attribution" in reasons:
            questions.append(
                "The generated explanation includes wording that may not be supported by its source. Please review source ‘"
                + source_text
                + "’ against explanation ‘"
                + claim.text
                + "’ and clarify the unsupported detail."
            )
            continue
        if reasons.intersection({"contradictory_medication_instructions", "instruction_polarity_mismatch", "high_alert_medication_review", "unsupported_medication_name"}):
            questions.append(
                "Please review source ‘" + source_text + "’ against explanation ‘" + claim.text
                + "’ and clarify the flagged uncertainty before this claim is used."
            )

    # Surface the most safety-relevant clarifications first across claims.
    unique_questions = list(dict.fromkeys(questions))
    def priority(question: str) -> int:
        if "source medication instruction is ambiguous" in question:
            return 0
        if "configured frequency safety review" in question:
            return 1
        if "Which frequency should be communicated" in question:
            return 2
        return 3
    return sorted(unique_questions, key=priority)
