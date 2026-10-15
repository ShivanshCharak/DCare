from fastapi import HTTPException

from app.main import review_claim, review_queue, review_source_sentence
from app.models import (
    Claim,
    ClaimReviewRequest,
    DocumentRecord,
    Fact,
    ReviewAction,
    Sentence,
    State,
)
from app.store import store


def setup_function():
    store.documents.clear()

    sentence = Sentence(
        id="S1",
        text="Take paracetamol 500 mg twice daily.",
        section="medications",
    )

    claim = Claim(
        id="C1",
        text="Take paracetamol 500 mg twice daily.",
        language="en",
        fact_ids=["F1"],
        source_ids=["S1"],
        state=State.REVIEW_SUGGESTED,
        reason_codes=["verification_layers_not_fully_configured"],
        checks={},
    )

    document = DocumentRecord(
        id="D1",
        source_name="synthetic-test",
        original_text=sentence.text,
        sentences=[sentence],
        facts=[Fact(id="F1", kind="medication", text_en=sentence.text, source_ids=[sentence.id])],
        claims=[claim],
        status="explained",
    )

    store.documents[document.id] = document


def test_approve_records_review_without_marking_verified():
    result = review_claim(
        "C1",
        ClaimReviewRequest(action="approve", reviewer="test-reviewer"),
    )

    assert result.recorded is True
    assert result.state == State.REVIEW_SUGGESTED
    assert result.reviewer_action == ReviewAction.APPROVE

    claim = store.documents["D1"].claims[0]
    assert claim.review is not None
    assert claim.state == State.REVIEW_SUGGESTED


def test_edit_updates_text_and_requires_reverification():
    result = review_claim(
        "C1",
        ClaimReviewRequest(
            action="edit",
            reviewer="test-reviewer",
            edited_text="Take paracetamol as directed by your clinician.",
        ),
    )

    assert result.state == State.NEEDS_CLINICIAN
    claim = store.documents["D1"].claims[0]
    assert claim.text == "Take paracetamol as directed by your clinician."
    assert claim.state == State.NEEDS_CLINICIAN
    assert claim.checks["source_ids"] == "passed"
    assert "unsupported_attribution" in claim.reason_codes
    assert claim.review_history[0].state_before == State.REVIEW_SUGGESTED
    assert claim.review_history[0].state_after == State.NEEDS_CLINICIAN
    assert len(claim.review_history) == 1
    assert any(item.claim.id == "C1" for item in review_queue())


def test_empty_edit_is_rejected_without_modifying_claim():
    claim = store.documents["D1"].claims[0]
    original_text = claim.text
    original_review = claim.review

    try:
        review_claim(
            "C1",
            ClaimReviewRequest(action="edit", edited_text="   "),
        )
    except HTTPException as exc:
        assert exc.status_code == 422
    else:
        raise AssertionError("Expected an empty edit to be rejected")

    assert claim.text == original_text
    assert claim.review == original_review


def test_reject_records_review():
    result = review_claim(
        "C1",
        ClaimReviewRequest(
            action="reject",
            reviewer="test-reviewer",
            note="Needs correction.",
        ),
    )

    assert result.reviewer_action == ReviewAction.REJECT
    claim = store.documents["D1"].claims[0]
    assert claim.review is not None
    assert claim.review.action.value == "reject"
    assert claim.state == State.NEEDS_CLINICIAN
    assert "human_rejected" in claim.reason_codes


def test_reviewed_claim_is_removed_from_review_queue():
    assert len(review_queue()) == 1

    review_claim(
        "C1",
        ClaimReviewRequest(action="approve", reviewer="test-reviewer"),
    )

    assert review_queue() == []


def test_unknown_claim_returns_404():
    try:
        review_claim(
            "DOES-NOT-EXIST",
            ClaimReviewRequest(action="approve"),
        )
    except HTTPException as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("Expected an unknown claim to return 404")


def test_source_sentence_review_removes_unclassified_sentence_from_queue():
    doc = store.documents["D1"]
    doc.sentences.append(Sentence(id="S2", text="Allergy status not confirmed.", section="unknown"))
    store.documents["D1"] = doc
    assert any(item.source_sentence and item.source_sentence.id == "S2" for item in review_queue())

    response = review_source_sentence("D1", "S2")

    assert response["recorded"] is True
    assert not any(item.source_sentence and item.source_sentence.id == "S2" for item in review_queue())


def test_duplicate_claim_id_across_documents_is_rejected_without_mutation():
    original = store.documents["D1"]
    duplicate = original.model_copy(deep=True)
    duplicate.id = "D2"
    duplicate.claims[0].review = None
    store.documents[duplicate.id] = duplicate

    try:
        review_claim("C1", ClaimReviewRequest(action="approve", reviewer="test-reviewer"))
    except HTTPException as exc:
        assert exc.status_code == 409
    else:
        raise AssertionError("Expected an ambiguous claim ID to be rejected")

    assert store.documents["D1"].claims[0].review is None
    assert store.documents["D2"].claims[0].review is None
