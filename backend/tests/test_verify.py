from app.models import Claim, Fact, Sentence, State
from app.pipeline.verify import (
    check_ambiguous_medication_details,
    check_unsupported_attributions,
    check_unsupported_numeric_details,
    check_instruction_polarity,
    check_medication_consistency,
    extract_frequencies,
    extract_durations,
    extract_timings,
    check_unsupported_medication_names,
    find_conflicting_medication_fact_ids,
    verify_claims,
)
from app.pipeline.route import build_doctor_questions


def make_medication_fact() -> Fact:
    return Fact(
        id="F1",
        kind="medication",
        text_en="Amlodipine 5 mg once daily.",
        attrs={
            "dose": "5 mg",
            "frequency": "once daily",
        },
        source_ids=["S1"],
    )


def make_claim(text: str) -> Claim:
    return Claim(
        id="C1",
        text=text,
        language="en",
        fact_ids=["F1"],
        source_ids=["S1"],
    )


def test_exact_medication_instruction_passes_deterministic_checks():
    sentences = [
        Sentence(
            id="S1",
            text="Amlodipine 5 mg once daily.",
            section="medications",
        )
    ]
    facts = [make_medication_fact()]
    claims = [make_claim("Amlodipine 5 mg once daily.")]

    result = verify_claims(claims, sentences, facts)

    assert result[0].checks["source_ids"] == "passed"
    assert result[0].checks["exact_match"] == "passed"
    assert result[0].checks["risk_rules"] == "passed"
    assert result[0].checks["medication_names"] == "passed"
    assert result[0].state == State.SOURCE_SUPPORTED


def test_daily_and_once_a_day_list_labeled_medication_wording_is_source_supported():
    source = "Amlodipine 5 mg daily."
    sentence = Sentence(id="S1", text=source, section="medications")
    fact = Fact(id="F1", kind="medication", text_en=source, source_ids=["S1"])
    claim = Claim(
        id="C1", text="B. Amlodipine 5 mg once a day.",
        fact_ids=["F1"], source_ids=["S1"],
    )

    result = verify_claims([claim], [sentence], [fact])[0]

    assert result.checks["risk_rules"] == "passed"
    assert result.checks["exact_match"] == "informational"
    assert result.state == State.SOURCE_SUPPORTED
    assert "human_review_recommended" not in result.reason_codes


def test_exact_source_copy_skips_entailment_judge(monkeypatch):
    source = "Stable condition."
    sentence = Sentence(id="S1", text=source, section="diagnosis")
    fact = Fact(id="F1", kind="diagnosis", text_en=source, source_ids=["S1"])

    def fail_if_called(*args, **kwargs):
        raise AssertionError("exact source copies must skip the entailment judge")

    monkeypatch.setattr("app.pipeline.verify.check_claim_entailment", fail_if_called)
    result = verify_claims(
        [Claim(id="C1", text=source, fact_ids=["F1"], source_ids=["S1"])],
        [sentence],
        [fact],
    )[0]

    assert result.checks["exact_match"] == "passed"
    assert result.checks["entailment_judge"] == "passed"
    assert "unsupported_claim_detail" not in result.reason_codes


def test_generic_medicine_wording_does_not_trigger_medication_rules():
    source = "Do not take medicine not prescribed to you."
    sentence = Sentence(id="S1", text=source, section="medications")
    fact = Fact(id="F1", kind="medication", text_en=source, source_ids=["S1"])
    claim = Claim(id="C1", text=source, fact_ids=["F1"], source_ids=["S1"])

    result = verify_claims([claim], [sentence], [fact])[0]

    assert result.checks["risk_rules"] == "not_applicable"
    assert result.checks["ambiguous_medication_details"] == "not_applicable"
    assert result.checks["medication_names"] == "not_applicable"
    assert not any("medication_" in reason or "ambiguous_medication" in reason for reason in result.reason_codes)


def test_known_medication_name_added_to_claim_routes_to_clinician():
    fact = make_medication_fact()
    claim = make_claim("Take amoxicillin and amlodipine 5 mg once daily.")

    status, problems = check_unsupported_medication_names(claim, [fact])
    assert status == "failed"
    assert problems == ["unsupported_medication_name"]

    sentence = Sentence(id="S1", text=fact.text_en, section="medications")
    result = verify_claims([claim], [sentence], [fact])[0]
    assert result.checks["medication_names"] == "failed"
    assert result.state == State.NEEDS_CLINICIAN


def test_common_ingredient_aliases_share_a_canonical_medication():
    fact = Fact(
        id="F1",
        kind="medication",
        text_en="Take paracetamol as listed.",
        source_ids=["S1"],
    )
    claim = make_claim("Take acetaminophen as listed.")
    assert check_unsupported_medication_names(claim, [fact]) == ("passed", [])


def test_changed_medication_dose_requires_clinician():
    sentences = [
        Sentence(
            id="S1",
            text="Amlodipine 5 mg once daily.",
            section="medications",
        )
    ]
    facts = [make_medication_fact()]
    claims = [make_claim("Amlodipine 10 mg once daily.")]

    result = verify_claims(claims, sentences, facts)

    assert result[0].checks["risk_rules"] == "failed"
    assert "medication_dose_mismatch" in result[0].reason_codes
    assert result[0].state == State.NEEDS_CLINICIAN


def test_changed_medication_frequency_requires_clinician():
    sentences = [
        Sentence(
            id="S1",
            text="Amlodipine 5 mg once daily.",
            section="medications",
        )
    ]
    facts = [make_medication_fact()]
    claims = [make_claim("Amlodipine 5 mg twice daily.")]

    result = verify_claims(claims, sentences, facts)

    assert result[0].checks["risk_rules"] == "failed"
    assert "medication_frequency_mismatch" in result[0].reason_codes
    assert result[0].state == State.NEEDS_CLINICIAN


def test_as_needed_must_not_be_rewritten_as_duration():
    source = "Take amlodipine as needed for fever."
    sentence = Sentence(id="S1", text=source, section="medications")
    fact = Fact(id="F1", kind="medication", text_en=source, source_ids=["S1"])
    claim = make_claim("Take amlodipine for as long as needed for fever.")

    result = verify_claims([claim], [sentence], [fact])[0]

    assert result.checks["risk_rules"] == "failed"
    assert "as_needed_duration_added" in result.reason_codes
    assert result.state == State.NEEDS_CLINICIAN


def test_as_needed_fever_instruction_catches_duration_rewording():
    source = "Use albuterol when you have a fever, as needed."
    sentence = Sentence(id="S1", text=source, section="medications")
    fact = Fact(id="F1", kind="medication", text_en=source, source_ids=["S1"])
    claim = make_claim("Use albuterol when you have a fever, as long as needed.")

    result = verify_claims([claim], [sentence], [fact])[0]

    assert result.checks["risk_rules"] == "failed"
    assert "as_needed_duration_added" in result.reason_codes


def test_softened_urgent_warning_instruction_is_flagged():
    source = "Seek urgent medical care if breathing becomes difficult."
    sentence = Sentence(id="S1", text=source, section="warning_signs")
    fact = Fact(id="F1", kind="warning_sign", text_en=source, source_ids=["S1"])
    claim = Claim(
        id="C1", text="See a doctor right away if breathing becomes difficult.",
        fact_ids=["F1"], source_ids=["S1"],
    )

    result = verify_claims([claim], [sentence], [fact])[0]

    assert result.checks["warning_sign_urgency"] == "failed"
    assert "warning_sign_escalation_softened" in result.reason_codes
    assert result.check_details["warning_sign_urgency"].message.startswith("The explanation lowers the response level")
    assert result.state == State.NEEDS_CLINICIAN


def test_known_harmless_paraphrase_skips_judge_and_ranks_below_dose_error(monkeypatch):
    source = "Do not take medication not prescribed to you."
    sentence = Sentence(id="S1", text=source, section="medications")
    fact = Fact(id="F1", kind="medication", text_en=source, source_ids=["S1"])
    paraphrase = Claim(
        id="C5", text="Do not take medicine not prescribed for you.",
        fact_ids=["F1"], source_ids=["S1"],
    )
    def fail_if_called(*args, **kwargs):
        raise AssertionError("recognized wording equivalents should skip the small model judge")

    monkeypatch.setattr("app.pipeline.verify.check_claim_entailment", fail_if_called)
    paraphrase_result = verify_claims([paraphrase], [sentence], [fact])[0]

    dose_source = "Take amlodipine 5 mg once daily."
    dose_sentence = Sentence(id="S2", text=dose_source, section="medications")
    dose_fact = Fact(id="F2", kind="medication", text_en=dose_source, source_ids=["S2"])
    dose_claim = Claim(
        id="C-dose", text="Take amlodipine 10 mg once daily.",
        fact_ids=["F2"], source_ids=["S2"],
    )
    monkeypatch.setattr(
        "app.pipeline.verify.check_claim_entailment",
        lambda *args, **kwargs: ("passed", []),
    )
    dose_result = verify_claims([dose_claim], [dose_sentence], [dose_fact])[0]

    assert paraphrase_result.checks["entailment_judge"] == "not_applicable"
    assert "unsupported_claim_detail" not in paraphrase_result.reason_codes
    assert "uncertain_claim_entailment" not in paraphrase_result.reason_codes
    assert "human_review_recommended" not in paraphrase_result.reason_codes
    assert paraphrase_result.state == State.SOURCE_SUPPORTED
    assert paraphrase_result.review_priority_score < dose_result.review_priority_score


def test_exact_unusually_high_frequency_is_reviewed_and_routed_to_clinician():
    source = "Take the supromysin 10 times a day."
    sentence = Sentence(id="S1", text=source, section="medications")
    fact = Fact(id="F1", kind="medication", text_en=source, source_ids=["S1"])
    claim = make_claim(source)

    result = verify_claims([claim], [sentence], [fact])[0]

    assert result.checks["exact_match"] == "passed"
    assert result.check_details["exact_match"].message.endswith(
        "Text equality does not establish that a medication instruction is safe."
    )
    assert result.checks["risk_rules"] == "review_suggested"
    assert "medication_frequency_requires_clinician_review" in result.reason_codes
    assert result.state == State.NEEDS_CLINICIAN
    assert result.text == source
    questions = build_doctor_questions([fact], [result])
    assert len(questions) == 1
    assert "Do not infer a different schedule" in questions[0]


def test_unconfigured_or_unrun_checks_keep_explicit_results():
    sentence = Sentence(id="S1", text="Hypertension.", section="diagnosis")
    fact = Fact(id="F1", kind="diagnosis", text_en="Hypertension.", source_ids=["S1"])
    result = verify_claims([make_claim("Hypertension.")], [sentence], [fact])[0]

    assert result.checks["risk_rules"] == "not_applicable"
    assert result.check_details["risk_rules"].performed is False
    assert result.checks["back_translation"] == "not_applicable"
    assert result.check_details["back_translation"].performed is False


def test_frequency_synonyms_normalize_to_same_schedule():
    assert extract_frequencies("Take medication twice daily.") == ["twice_daily"]
    assert extract_frequencies("Take medication twice a day.") == ["twice_daily"]
    assert extract_frequencies("Take medication once daily.") == ["once_daily"]
    assert extract_frequencies("Take medication once a day.") == ["once_daily"]
    assert extract_frequencies("Take medication two times a day.") == ["twice_daily"]
    assert extract_frequencies("Take medication one time daily.") == ["once_daily"]


def test_once_daily_and_once_a_day_are_equivalent_in_source_claim_comparison():
    fact = Fact(
        id="F1",
        kind="medication",
        text_en="Take amlodipine 5 mg once daily.",
        source_ids=["S1"],
    )
    claim = make_claim("Take amlodipine 5 mg once a day.")

    assert extract_frequencies(fact.text_en) == ["once_daily"]
    assert extract_frequencies(claim.text) == ["once_daily"]
    assert check_medication_consistency(claim, [fact]) == ("passed", [])


def test_genuine_medication_frequency_change_still_fails_consistency():
    fact = Fact(
        id="F1",
        kind="medication",
        text_en="Take amlodipine 5 mg once daily.",
        source_ids=["S1"],
    )
    claim = make_claim("Take amlodipine 5 mg twice a day.")

    assert check_medication_consistency(claim, [fact]) == (
        "failed",
        ["medication_frequency_mismatch"],
    )


def test_written_number_medication_paraphrase_matches_source_details():
    fact = Fact(
        id="F1",
        kind="medication",
        text_en="Take metformin 500 mg twice daily for 5 days.",
        source_ids=["S1"],
    )
    claim = make_claim(
        "Take 500mg of metformin two times a day for five days."
    )
    assert check_medication_consistency(claim, [fact]) == ("passed", [])


def test_as_needed_frequency_synonyms_normalize_to_same_schedule():
    assert extract_frequencies("Take medication as needed.") == ["as_needed"]
    assert extract_frequencies("Take medication whenever you need it.") == ["as_needed"]

    fact = Fact(
        id="F1",
        kind="medication",
        text_en="Take metformin 500 mg twice daily as needed.",
        source_ids=["S1"],
    )
    equivalent_claim = make_claim("Take metformin 500 mg twice a day whenever you need it.")
    missing_prn_claim = make_claim("Take metformin 500 mg twice a day.")
    assert check_medication_consistency(equivalent_claim, [fact]) == ("passed", [])
    assert check_medication_consistency(missing_prn_claim, [fact]) == (
        "failed",
        ["medication_frequency_mismatch"],
    )


def test_unknown_source_requires_clinician():
    sentences = [
        Sentence(
            id="S1",
            text="Amlodipine 5 mg once daily.",
            section="medications",
        )
    ]
    facts = [make_medication_fact()]
    claim = make_claim("Amlodipine 5 mg once daily.")
    claim.source_ids = ["S999"]

    result = verify_claims([claim], sentences, facts)

    assert result[0].checks["source_ids"] == "failed"
    assert "invalid_or_missing_source" in result[0].reason_codes
    assert result[0].state == State.NEEDS_CLINICIAN


def test_non_medication_claim_does_not_run_medication_rules():
    sentences = [
        Sentence(
            id="S1",
            text="Hypertension.",
            section="diagnosis",
        )
    ]
    facts = [
        Fact(
            id="F1",
            kind="diagnosis",
            text_en="Hypertension.",
            attrs={},
            source_ids=["S1"],
        )
    ]
    claims = [
        Claim(
            id="C1",
            text="Hypertension.",
            language="en",
            fact_ids=["F1"],
            source_ids=["S1"],
        )
    ]

    result = verify_claims(claims, sentences, facts)

    assert result[0].checks["risk_rules"] == "not_applicable"
    assert result[0].state == State.SOURCE_SUPPORTED


def test_unknown_fact_requires_clinician():
    sentences = [
        Sentence(
            id="S1",
            text="Amlodipine 5 mg once daily.",
            section="medications",
        )
    ]

    facts = [make_medication_fact()]
    claim = make_claim("Amlodipine 5 mg once daily.")
    claim.fact_ids = ["F999"]

    result = verify_claims([claim], sentences, facts)

    assert result[0].checks["source_ids"] == "failed"
    assert "invalid_or_missing_fact" in result[0].reason_codes
    assert result[0].state == State.NEEDS_CLINICIAN


def test_changed_medication_duration_requires_clinician():
    sentences = [
        Sentence(
            id="S1",
            text="Take amoxicillin for 5 days.",
            section="medications",
        )
    ]

    facts = [
        Fact(
            id="F1",
            kind="medication",
            text_en="Take amoxicillin for 5 days.",
            attrs={},
            source_ids=["S1"],
        )
    ]

    claim = Claim(
        id="C1",
        text="Take amoxicillin for 10 days.",
        language="en",
        fact_ids=["F1"],
        source_ids=["S1"],
    )

    result = verify_claims([claim], sentences, facts)

    assert result[0].checks["risk_rules"] == "failed"
    assert "medication_duration_mismatch" in result[0].reason_codes
    assert result[0].state == State.NEEDS_CLINICIAN


def test_verifier_marks_exact_source_supported_but_not_clinically_verified():
    sentences = [
        Sentence(
            id="S1",
            text="Hypertension.",
            section="diagnosis",
        )
    ]

    facts = [
        Fact(
            id="F1",
            kind="diagnosis",
            text_en="Hypertension.",
            attrs={},
            source_ids=["S1"],
        )
    ]

    claim = Claim(
        id="C1",
        text="Hypertension.",
        language="en",
        fact_ids=["F1"],
        source_ids=["S1"],
        state=State.VERIFIED,
    )

    result = verify_claims([claim], sentences, facts)

    assert result[0].state == State.SOURCE_SUPPORTED
    assert result[0].state != State.VERIFIED
    assert result[0].checks["entailment_judge"] == "passed"
    assert result[0].checks["back_translation"] == "not_applicable"


def test_changed_appointment_timeframe_is_not_exact_match():
    sentences = [
        Sentence(
            id="S1",
            text="Attend your follow-up appointment in 7 days.",
            section="follow_up",
        )
    ]

    facts = [
        Fact(
            id="F1",
            kind="appointment",
            text_en="Attend your follow-up appointment in 7 days.",
            attrs={},
            source_ids=["S1"],
        )
    ]

    claim = Claim(
        id="C1",
        text="Attend your follow-up appointment in 30 days.",
        language="en",
        fact_ids=["F1"],
        source_ids=["S1"],
    )

    result = verify_claims([claim], sentences, facts)

    assert result[0].checks["exact_match"] == "informational"
    assert result[0].checks["numeric_details"] == "failed"
    assert result[0].state == State.NEEDS_CLINICIAN


def test_flags_unsupported_doctor_attribution():
    source = Fact(
        id="F1",
        kind="diagnosis",
        text_en="Pneumonia was diagnosed.",
        source_ids=["S1"],
    )

    claim = Claim(
        id="C1",
        text="The doctor told the patient they have pneumonia.",
        language="en",
        fact_ids=["F1"],
        source_ids=["S1"],
    )

    status, problems = check_unsupported_attributions(claim, [source])

    assert status == "failed"
    assert problems == ["unsupported_attribution"]


def test_allows_diagnosis_paraphrase_without_attribution():
    source = Fact(
        id="F1",
        kind="diagnosis",
        text_en="Pneumonia was diagnosed.",
        source_ids=["S1"],
    )

    claim = Claim(
        id="C1",
        text="The patient has pneumonia.",
        language="en",
        fact_ids=["F1"],
        source_ids=["S1"],
    )

    status, problems = check_unsupported_attributions(claim, [source])

    assert status == "passed"
    assert problems == []


def test_does_not_flag_supported_doctor_attribution():
    source = Fact(
        id="F1",
        kind="diagnosis",
        text_en="The doctor told the patient they have pneumonia.",
        source_ids=["S1"],
    )

    claim = Claim(
        id="C1",
        text="The doctor told the patient they have pneumonia.",
        language="en",
        fact_ids=["F1"],
        source_ids=["S1"],
    )

    status, problems = check_unsupported_attributions(claim, [source])

    assert status == "passed"
    assert problems == []


def test_flags_unsupported_healthcare_provider_attribution():
    source = Fact(
        id="F1",
        kind="medication",
        text_en="Continue taking fentanyl as directed in the discharge paperwork.",
        source_ids=["S1"],
    )
    claim = Claim(
        id="C1",
        text="Take fentanyl as directed by your healthcare provider.",
        fact_ids=["F1"],
        source_ids=["S1"],
    )

    assert check_unsupported_attributions(claim, [source]) == (
        "failed",
        ["unsupported_attribution"],
    )


def test_synthetic_negation_paraphrase_is_not_instruction_polarity_change():
    source = Fact(
        id="F1",
        kind="diagnosis",
        text_en="A synthetic condition was documented during this hospital stay.",
        source_ids=["S1"],
    )
    claim = Claim(
        id="C1",
        text="A condition that is not naturally occurring was documented during this hospital stay.",
        fact_ids=["F1"],
        source_ids=["S1"],
    )

    assert check_instruction_polarity(claim, [source]) == ("passed", [])


def test_unsupported_attribution_routes_claim_to_clinician():
    sentences = [
        Sentence(id="S1", text="Pneumonia was diagnosed.", section="diagnosis")
    ]
    facts = [
        Fact(
            id="F1",
            kind="diagnosis",
            text_en="Pneumonia was diagnosed.",
            attrs={},
            source_ids=["S1"],
        )
    ]
    claim = Claim(
        id="C1",
        text="The doctor told the patient they have pneumonia.",
        language="en",
        fact_ids=["F1"],
        source_ids=["S1"],
    )

    result = verify_claims([claim], sentences, facts)

    assert result[0].checks["unsupported_details"] == "failed"
    assert "unsupported_attribution" in result[0].reason_codes
    assert result[0].state == State.NEEDS_CLINICIAN


def test_high_alert_medication_is_explicitly_routed_for_review():
    sentences = [
        Sentence(
            id="S1",
            text="Continue warfarin 2 mg once daily.",
            section="medications",
        )
    ]
    facts = [
        Fact(
            id="F1",
            kind="medication",
            text_en="Continue warfarin 2 mg once daily.",
            attrs={},
            source_ids=["S1"],
        )
    ]
    claim = Claim(
        id="C1",
        text="Continue warfarin 2 mg once daily.",
        language="en",
        fact_ids=["F1"],
        source_ids=["S1"],
    )

    result = verify_claims([claim], sentences, facts)

    assert result[0].checks["high_alert_medication"] == "review_suggested"
    assert "high_alert_medication_review" in result[0].reason_codes
    assert result[0].state == State.REVIEW_SUGGESTED


def test_flags_numeric_detail_absent_from_linked_source():
    source = Fact(
        id="F1",
        kind="appointment",
        text_en="Attend your follow-up appointment in 7 days.",
        source_ids=["S1"],
    )
    claim = Claim(
        id="C1",
        text="Attend your follow-up appointment in 30 days.",
        language="en",
        fact_ids=["F1"],
        source_ids=["S1"],
    )

    status, problems = check_unsupported_numeric_details(claim, [source])

    assert status == "failed"
    assert problems == ["unsupported_numeric_detail"]


def test_flags_numeric_date_absent_from_linked_source():
    source = Fact(
        id="F1",
        kind="appointment",
        text_en="Your appointment is on 10/20/2026.",
        source_ids=["S1"],
    )
    claim = Claim(
        id="C1",
        text="Your appointment is on 10/21/2026.",
        language="en",
        fact_ids=["F1"],
        source_ids=["S1"],
    )

    status, problems = check_unsupported_numeric_details(claim, [source])

    assert status == "failed"
    assert problems == ["unsupported_numeric_detail"]


def test_numeric_date_and_month_name_date_compare_equally():
    source = Fact(
        id="F1",
        kind="appointment",
        text_en="Your appointment is on 10/20/2026.",
        source_ids=["S1"],
    )
    claim = Claim(
        id="C1",
        text="Your appointment is scheduled for October 20, 2026.",
        fact_ids=["F1"],
        source_ids=["S1"],
    )

    assert check_unsupported_numeric_details(claim, [source]) == ("passed", [])


def test_numeric_check_normalizes_devanagari_digits():
    source = Fact(
        id="F1",
        kind="appointment",
        text_en="Attend your follow-up appointment in 7 days.",
        source_ids=["S1"],
    )
    claim = Claim(
        id="C1",
        text="अपने फॉलो-अप अपॉइंटमेंट पर ७ दिनों में आएँ।",
        language="hi",
        fact_ids=["F1"],
        source_ids=["S1"],
    )

    status, problems = check_unsupported_numeric_details(claim, [source])

    assert status == "passed"
    assert problems == []


def test_unsupported_numeric_detail_routes_claim_to_clinician():
    sentences = [
        Sentence(
            id="S1",
            text="Attend your follow-up appointment in 7 days.",
            section="follow_up",
        )
    ]
    facts = [
        Fact(
            id="F1",
            kind="appointment",
            text_en="Attend your follow-up appointment in 7 days.",
            attrs={},
            source_ids=["S1"],
        )
    ]
    claim = Claim(
        id="C1",
        text="Attend your follow-up appointment in 30 days.",
        language="en",
        fact_ids=["F1"],
        source_ids=["S1"],
    )

    result = verify_claims([claim], sentences, facts)

    assert result[0].checks["numeric_details"] == "failed"
    assert "unsupported_numeric_detail" in result[0].reason_codes
    assert result[0].state == State.NEEDS_CLINICIAN


def test_flags_dropped_negation():
    source = Fact(
        id="F1",
        kind="medication",
        text_en="Do not take aspirin.",
        source_ids=["S1"],
    )
    claim = Claim(
        id="C1",
        text="Take aspirin.",
        language="en",
        fact_ids=["F1"],
        source_ids=["S1"],
    )

    status, problems = check_instruction_polarity(claim, [source])

    assert status == "failed"
    assert problems == ["instruction_polarity_mismatch"]


def test_flags_added_negation():
    source = Fact(
        id="F1",
        kind="medication",
        text_en="Take aspirin.",
        source_ids=["S1"],
    )
    claim = Claim(
        id="C1",
        text="Do not take aspirin.",
        language="en",
        fact_ids=["F1"],
        source_ids=["S1"],
    )

    status, problems = check_instruction_polarity(claim, [source])

    assert status == "failed"
    assert problems == ["instruction_polarity_mismatch"]


def test_flags_stop_continue_conflict():
    source = Fact(
        id="F1",
        kind="medication",
        text_en="Stop taking warfarin.",
        source_ids=["S1"],
    )
    claim = Claim(
        id="C1",
        text="Continue taking warfarin.",
        language="en",
        fact_ids=["F1"],
        source_ids=["S1"],
    )

    status, problems = check_instruction_polarity(claim, [source])

    assert status == "failed"
    assert problems == ["instruction_polarity_mismatch"]


def test_flags_dropped_continue_instruction():
    source = Fact(
        id="F1",
        kind="medication",
        text_en="Continue taking warfarin as listed.",
        source_ids=["S1"],
    )
    claim = Claim(
        id="C1",
        text="Take warfarin as listed.",
        fact_ids=["F1"],
        source_ids=["S1"],
    )

    assert check_instruction_polarity(claim, [source]) == (
        "failed",
        ["instruction_polarity_mismatch"],
    )


def test_continue_instruction_synonym_passes_polarity_check():
    source = Fact(
        id="F1",
        kind="medication",
        text_en="Continue taking warfarin as listed.",
        source_ids=["S1"],
    )
    claim = Claim(
        id="C1",
        text="Keep taking warfarin as listed.",
        fact_ids=["F1"],
        source_ids=["S1"],
    )

    assert check_instruction_polarity(claim, [source]) == ("passed", [])


def test_matching_negation_passes_instruction_polarity_check():
    source = Fact(
        id="F1",
        kind="warning_sign",
        text_en="Do not drive while taking this medicine.",
        source_ids=["S1"],
    )
    claim = Claim(
        id="C1",
        text="Do not drive while taking this medicine.",
        language="en",
        fact_ids=["F1"],
        source_ids=["S1"],
    )

    status, problems = check_instruction_polarity(claim, [source])

    assert status == "passed"
    assert problems == []


def test_pending_status_rephrased_as_not_yet_available_is_not_negation_change():
    source = Fact(
        id="F1",
        kind="pending_test",
        text_en="The final laboratory report is pending.",
        source_ids=["S1"],
    )
    claim = Claim(
        id="C1",
        text="The final laboratory report is not yet available.",
        fact_ids=["F1"],
        source_ids=["S1"],
    )

    assert check_instruction_polarity(claim, [source]) == ("passed", [])


def test_finds_stop_continue_conflict_across_high_alert_facts():
    facts = [
        Fact(
            id="F1",
            kind="medication",
            text_en="Stop taking warfarin.",
            source_ids=["S1"],
        ),
        Fact(
            id="F2",
            kind="medication",
            text_en="Continue taking warfarin.",
            source_ids=["S2"],
        ),
    ]

    assert find_conflicting_medication_fact_ids(facts) == {"F1", "F2"}


def test_finds_stop_continue_conflict_for_supplemental_medication_name():
    facts = [
        Fact(id="F1", kind="medication", text_en="Stop amlodipine.", source_ids=["S1"]),
        Fact(id="F2", kind="medication", text_en="Continue amlodipine.", source_ids=["S2"]),
    ]

    assert find_conflicting_medication_fact_ids(facts) == {"F1", "F2"}


def test_finds_dose_frequency_and_duration_conflicts_for_same_medication():
    conflicting_pairs = [
        (
            "Take metformin 500 mg twice daily for 5 days.",
            "Take metformin 1000 mg twice daily for 5 days.",
        ),
        (
            "Take metformin 500 mg once daily for 5 days.",
            "Take metformin 500 mg twice daily for 5 days.",
        ),
        (
            "Take metformin 500 mg twice daily for 5 days.",
            "Take metformin 500 mg twice daily for 10 days.",
        ),
    ]
    for first, second in conflicting_pairs:
        facts = [
            Fact(id="F1", kind="medication", text_en=first, source_ids=["S1"]),
            Fact(id="F2", kind="medication", text_en=second, source_ids=["S2"]),
        ]
        assert find_conflicting_medication_fact_ids(facts) == {"F1", "F2"}


def test_does_not_flag_same_medication_details_when_one_fact_is_unspecified():
    facts = [
        Fact(
            id="F1",
            kind="medication",
            text_en="Take metformin 500 mg twice daily.",
            source_ids=["S1"],
        ),
        Fact(
            id="F2",
            kind="medication",
            text_en="Metformin is included on the medication list.",
            source_ids=["S2"],
        ),
    ]
    assert find_conflicting_medication_fact_ids(facts) == set()


def test_negated_stop_is_not_treated_as_a_stop_directive():
    facts = [
        Fact(
            id="F1",
            kind="medication",
            text_en="Do not stop taking warfarin.",
            source_ids=["S1"],
        ),
        Fact(
            id="F2",
            kind="medication",
            text_en="Continue taking warfarin.",
            source_ids=["S2"],
        ),
    ]

    assert find_conflicting_medication_fact_ids(facts) == set()


def test_cross_fact_medication_conflict_routes_linked_claim_to_clinician():
    sentences = [
        Sentence(id="S1", text="Stop taking warfarin.", section="medications"),
        Sentence(id="S2", text="Continue taking warfarin.", section="medications"),
    ]
    facts = [
        Fact(
            id="F1",
            kind="medication",
            text_en="Stop taking warfarin.",
            attrs={},
            source_ids=["S1"],
        ),
        Fact(
            id="F2",
            kind="medication",
            text_en="Continue taking warfarin.",
            attrs={},
            source_ids=["S2"],
        ),
    ]
    claim = Claim(
        id="C1",
        text="Stop taking warfarin.",
        language="en",
        fact_ids=["F1"],
        source_ids=["S1"],
    )

    result = verify_claims([claim], sentences, facts)

    assert result[0].checks["medication_contradictions"] == "failed"
    assert "contradictory_medication_instructions" in result[0].reason_codes
    assert result[0].state == State.NEEDS_CLINICIAN


def test_cross_fact_dose_conflict_routes_linked_claim_to_clinician():
    sentences = [
        Sentence(
            id="S1",
            text="Take metformin 500 mg twice daily for 5 days.",
            section="medications",
        ),
        Sentence(
            id="S2",
            text="Take metformin 1000 mg twice daily for 5 days.",
            section="medications",
        ),
    ]
    facts = [
        Fact(
            id="F1",
            kind="medication",
            text_en=sentences[0].text,
            source_ids=["S1"],
        ),
        Fact(
            id="F2",
            kind="medication",
            text_en=sentences[1].text,
            source_ids=["S2"],
        ),
    ]
    claim = Claim(
        id="C1",
        text=sentences[0].text,
        fact_ids=["F1"],
        source_ids=["S1"],
    )

    result = verify_claims([claim], sentences, facts)[0]
    assert result.checks["medication_contradictions"] == "failed"
    assert "contradictory_medication_instructions" in result.reason_codes
    assert result.state == State.NEEDS_CLINICIAN


def test_ambiguous_numeric_medication_instruction_is_review_suggested():
    fact = Fact(
        id="F1",
        kind="medication",
        text_en="Take amlodipine 5 once daily.",
        source_ids=["S1"],
    )

    status, problems = check_ambiguous_medication_details([fact])

    assert status == "review_suggested"
    assert problems == ["ambiguous_medication_details"]


def test_clear_medication_instruction_passes_ambiguity_check():
    fact = Fact(
        id="F1",
        kind="medication",
        text_en="Take amlodipine 5 mg once daily.",
        source_ids=["S1"],
    )

    status, problems = check_ambiguous_medication_details([fact])

    assert status == "passed"
    assert problems == []


def test_high_alert_dose_change_requires_clinician():
    sentences = [
        Sentence(id="S1", text="Take warfarin 2 mg once daily.", section="medications")
    ]
    facts = [
        Fact(
            id="F1",
            kind="medication",
            text_en="Take warfarin 2 mg once daily.",
            attrs={},
            source_ids=["S1"],
        )
    ]
    claim = Claim(
        id="C1",
        text="Take warfarin 5 mg once daily.",
        language="en",
        fact_ids=["F1"],
        source_ids=["S1"],
    )

    result = verify_claims([claim], sentences, facts)

    assert result[0].checks["high_alert_medication"] == "review_suggested"
    assert "medication_dose_mismatch" in result[0].reason_codes
    assert result[0].state == State.NEEDS_CLINICIAN


def test_frequency_mismatch_case_ten_times_daily_to_once_daily_needs_clinician():
    sentence = Sentence(
        id="S1",
        text="Take warfarin 5 mg 10 times a day in the evening.",
        section="medications",
    )
    fact = Fact(id="F1", kind="medication", text_en=sentence.text, source_ids=["S1"])
    claim = make_claim("Take warfarin 5 mg every day in the evening.")
    result = verify_claims([claim], [sentence], [fact])[0]

    assert result.checks["risk_rules"] == "failed"
    assert "medication_frequency_mismatch" in result.reason_codes
    assert result.state == State.NEEDS_CLINICIAN
    assert result.check_details["risk_rules"].reason_code == "medication_frequency_mismatch"
    assert result.check_details["risk_rules"].source_text == sentence.text
    assert result.check_details["risk_rules"].claim_text == claim.text
    assert result.check_details["risk_rules"].performed is True


def test_ambiguous_days_per_week_instruction_is_not_reinterpreted():
    sentence = Sentence(
        id="S1", text="take supromysin 10 days a week", section="medications"
    )
    fact = Fact(id="F1", kind="medication", text_en=sentence.text, source_ids=["S1"])
    claim = make_claim("Take supromysin every day, for 10 days.")
    result = verify_claims([claim], [sentence], [fact])[0]

    assert "ambiguous_medication_schedule" in result.reason_codes
    assert "interpreted_ambiguous_medication_schedule" in result.reason_codes
    assert "medication_frequency_mismatch" not in result.reason_codes
    assert result.checks["unsupported_details"] == "failed"
    assert result.state == State.NEEDS_CLINICIAN


def test_ten_times_a_week_is_ambiguous_and_requires_clinician_review():
    wording = "Take the medicines as listed in the 10 times a week."
    sentence = Sentence(id="S1", text=wording, section="medications")
    fact = Fact(id="F1", kind="medication", text_en=wording, source_ids=["S1"])
    claim = make_claim(wording)
    result = verify_claims([claim], [sentence], [fact])[0]

    assert result.text == wording
    assert "ambiguous_medication_schedule" in result.reason_codes
    assert result.state == State.NEEDS_CLINICIAN
    assert result.checks["exact_match"] == "passed"
    assert result.checks["risk_rules"] == "review_suggested"
    assert result.check_details["risk_rules"].source_text == wording
    assert result.check_details["risk_rules"].claim_text == wording


def test_frequency_recognized_as_valid_expression_is_not_called_malformed():
    assert extract_frequencies("Take amlodipine 5 mg twice daily.") == ["twice_daily"]
    assert extract_frequencies("Take amlodipine 5 mg 10 times a week.") == []


def test_equivalent_wording_does_not_become_a_semantic_failure():
    sentence = Sentence(
        id="S1",
        text="Ask your care team whether the pending test has been completed.",
        section="pending_test",
    )
    fact = Fact(id="F1", kind="pending_test", text_en=sentence.text, source_ids=["S1"])
    claim = make_claim("Ask your care team if the pending test has been completed.")
    result = verify_claims([claim], [sentence], [fact])[0]

    assert result.checks["exact_match"] == "informational"
    assert "unsupported_claim_detail" not in result.reason_codes
    assert "instruction_polarity_mismatch" not in result.reason_codes
    assert result.check_details["exact_match"].performed is True


def test_medication_class_added_from_outside_knowledge_is_flagged():
    sentence = Sentence(id="S1", text="Take Zorvex 250 mg twice daily.", section="medications")
    fact = Fact(id="F1", kind="medication", text_en=sentence.text, source_ids=["S1"])
    claim = make_claim("Take Zorvex 250 mg twice daily. Zorvex is a type of antibiotic.")

    result = verify_claims([claim], [sentence], [fact])[0]

    assert result.checks["medication_context"] == "failed"
    assert "unsupported_medication_context" in result.reason_codes
    assert result.state == State.NEEDS_CLINICIAN


def test_generated_medication_frequency_absent_from_source_is_unsupported():
    sentence = Sentence(
        id="S1",
        text="Take the medication as instructed on the prescription label.",
        section="medications",
    )
    fact = Fact(id="F1", kind="medication", text_en=sentence.text, source_ids=["S1"])
    claim = make_claim("Take the medication twice daily.")
    result = verify_claims([claim], [sentence], [fact])[0]

    assert "unsupported_medication_frequency" in result.reason_codes
    assert result.checks["unsupported_details"] == "failed"
    assert result.state == State.NEEDS_CLINICIAN


def test_unrecognized_empty_schedule_is_uncertain_not_a_pass():
    sentence = Sentence(
        id="S1", text="Take the medication as directed.", section="medications"
    )
    fact = Fact(id="F1", kind="medication", text_en=sentence.text, source_ids=["S1"])
    claim = make_claim(sentence.text)
    result = verify_claims([claim], [sentence], [fact])[0]

    assert result.checks["risk_rules"] == "passed"
    assert result.checks["ambiguous_medication_details"] == "review_suggested"
    assert "ambiguous_medication_details" in result.reason_codes
    assert result.state == State.REVIEW_SUGGESTED


def test_unconfigured_checks_are_not_passed_and_claim_stays_unverified(monkeypatch):
    sentence = Sentence(id="S1", text="Hypertension.", section="diagnosis")
    fact = Fact(id="F1", kind="diagnosis", text_en=sentence.text, source_ids=["S1"])
    monkeypatch.setattr("app.pipeline.verify.settings.entailment_judge_enabled", False)
    result = verify_claims([Claim(id="C1", text="High blood pressure.", fact_ids=["F1"], source_ids=["S1"])], [sentence], [fact])[0]

    detail = result.check_details["entailment_judge"]
    assert detail.status in {"not_configured", "not_run"}
    assert detail.performed is False
    assert any(
        phrase in detail.message
        for phrase in ("did not run", "did not complete", "not configured")
    )
    assert result.checks["unsupported_details"] == "review_suggested"
    assert "unsupported_details_check_incomplete" in result.reason_codes
    assert result.state != State.VERIFIED


def test_timing_is_checked_separately_from_frequency():
    source = Fact(
        id="F1", kind="medication",
        text_en="Take amlodipine 5 mg once daily in the evening.", source_ids=["S1"],
    )
    assert extract_frequencies(source.text_en) == ["once_daily"]
    assert extract_timings(source.text_en) == ["evening"]
    assert extract_durations(source.text_en) == []
    assert check_medication_consistency(
        make_claim("Take amlodipine 5 mg once daily in the morning."), [source]
    ) == ("failed", ["medication_timing_mismatch"])


def test_arbitrary_numeric_frequency_and_interval_are_extracted():
    assert extract_frequencies("Take medication 5 times a day.") == ["5_times_per_day"]
    assert extract_frequencies("Take medication 2 times per week.") == ["2_times_per_week"]
    assert extract_frequencies("Take medication every 6 hours.") == ["every_6_hours"]
    assert extract_frequencies("Take medication 5 times daily.") == ["5_times_per_day"]
    assert extract_frequencies("Take medication 3 times daily.") == ["three_times_daily"]
    assert extract_frequencies("Take medication as directed on its label.") == []
