from app.models import Claim, Fact, State
from app.pipeline.route import build_doctor_questions, combine_states

def test_worst_state_wins():
    assert combine_states([State.VERIFIED, State.REVIEW_SUGGESTED]) == State.REVIEW_SUGGESTED
    assert combine_states([State.VERIFIED, State.NEEDS_CLINICIAN]) == State.NEEDS_CLINICIAN


def test_doctor_questions_focus_on_ambiguous_medication_source_wording():
    fact = Fact(
        id="F1", kind="medication", text_en="take supromysin 10 days a week",
        source_ids=["S1"],
    )
    claim = Claim(
        id="C1", text="Take supromysin every day, for 10 days.",
        fact_ids=["F1"], source_ids=["S1"], state=State.NEEDS_CLINICIAN,
        reason_codes=["ambiguous_medication_schedule", "interpreted_ambiguous_medication_schedule"],
    )
    questions = build_doctor_questions([fact], [claim])
    assert len(questions) == 1
    assert fact.text_en in questions[0]
    assert "clarify the intended instruction" in questions[0]
    assert "generated schedule is correct" in questions[0]


def test_doctor_questions_omit_generic_questions_for_straightforward_claims():
    fact = Fact(
        id="F1", kind="diagnosis", text_en="Pneumonia was diagnosed.",
        source_ids=["S1"],
    )
    claim = Claim(
        id="C1", text="You were diagnosed with pneumonia.",
        fact_ids=["F1"], source_ids=["S1"], state=State.REVIEW_SUGGESTED,
    )
    assert build_doctor_questions([fact], [claim]) == []


def test_doctor_question_describes_as_needed_duration_change():
    fact = Fact(
        id="F1", kind="medication",
        text_en="Take paracetamol 500 mg as needed for fever.", source_ids=["S1"],
    )
    claim = Claim(
        id="C1", text="Take paracetamol 500 mg for as long as needed for fever.",
        fact_ids=["F1"], source_ids=["S1"], state=State.NEEDS_CLINICIAN,
        reason_codes=["as_needed_duration_added"],
    )
    questions = build_doctor_questions([fact], [claim])
    assert len(questions) == 1
    assert "only when needed" in questions[0]


def test_urgent_warning_question_is_generated_for_reviewers():
    fact = Fact(
        id="F1", kind="warning_sign",
        text_en="Seek urgent medical care if breathing becomes difficult.",
        source_ids=["S1"],
    )
    claim = Claim(
        id="C1", text="See a doctor right away if breathing becomes difficult.",
        fact_ids=["F1"], source_ids=["S1"], state=State.NEEDS_CLINICIAN,
        reason_codes=["warning_sign_escalation_softened"],
    )
    questions = build_doctor_questions([fact], [claim])
    assert len(questions) == 1
    assert "Should the urgent medical care instruction be restored?" in questions[0]
