from types import SimpleNamespace

from app.config import settings
from app.models import Claim, Fact, Sentence, State
from app.pipeline import entailment
from app.pipeline.verify import verify_claims


def model_response(verdict: str, unsupported_details=None):
    content = entailment.EntailmentAssessment(
        verdict=verdict,
        unsupported_details=unsupported_details or [],
    ).model_dump_json()
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def test_entailment_judge_uses_local_model_schema_and_marks_support(monkeypatch):
    captured = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return model_response("supported")

    monkeypatch.setattr(entailment, "chat_completion", fake_completion)
    status, reasons = entailment.check_claim_entailment(
        "Return in 7 days.", ["Follow up in 7 days."], enabled=True
    )

    assert status == "passed"
    assert reasons == []
    assert captured["response_format"]["json_schema"]["strict"] is True
    assert "Follow up in 7 days." in captured["messages"][1]["content"]


def test_entailment_judge_maps_unsupported_and_uncertain_to_review(monkeypatch):
    monkeypatch.setattr(
        entailment,
        "chat_completion",
        lambda **kwargs: model_response("unsupported", ["14 days"]),
    )
    assert entailment.check_claim_entailment(
        "Return in 14 days.", ["Follow up in 7 days."], enabled=True
    ) == ("failed", ["unsupported_claim_detail"])

    monkeypatch.setattr(
        entailment,
        "chat_completion",
        lambda **kwargs: model_response("uncertain"),
    )
    assert entailment.check_claim_entailment(
        "Return soon.", ["Follow up."], enabled=True
    ) == ("review_suggested", ["uncertain_claim_entailment"])


def test_entailment_disabled_does_not_call_model(monkeypatch):
    def unexpected_call(**kwargs):
        raise AssertionError("disabled judge must not call Ollama")

    monkeypatch.setattr(entailment, "chat_completion", unexpected_call)
    assert entailment.check_claim_entailment("Claim", ["Source"], enabled=False) == (
        "not_configured",
        [],
    )


def test_unsupported_judge_result_is_uncertain_not_definitive(monkeypatch):
    sentence = Sentence(id="S1", text="Follow up in 7 days.", section="follow_up")
    fact = Fact(
        id="F1",
        kind="appointment",
        text_en=sentence.text,
        source_ids=[sentence.id],
    )
    claim = Claim(
        id="C1",
        text="Follow up soon.",
        fact_ids=[fact.id],
        source_ids=[sentence.id],
    )
    monkeypatch.setattr(settings, "entailment_judge_enabled", True)
    monkeypatch.setattr(
        "app.pipeline.verify.check_claim_entailment",
        lambda *args, **kwargs: ("failed", ["unsupported_claim_detail"]),
    )

    result = verify_claims([claim], [sentence], [fact])[0]
    assert result.checks["entailment_judge"] == "review_suggested"
    assert "uncertain_claim_entailment" in result.reason_codes
    assert "unsupported_claim_detail" not in result.reason_codes
    assert result.state == State.REVIEW_SUGGESTED
