from types import SimpleNamespace

from app.models import Fact
from app.pipeline import explain


def test_failed_model_call_keeps_source_claim_and_marks_generation_failure(monkeypatch):
    fact = Fact(
        id="F1", kind="medication", text_en="Take the fictional medicine as listed.",
        source_ids=["S7"],
    )

    def unavailable_model(**_kwargs):
        raise TimeoutError("synthetic model timeout")

    monkeypatch.setattr(explain, "chat_completion", unavailable_model)
    claims = explain.explain_facts([fact])

    assert len(claims) == 1
    assert claims[0].text == fact.text_en
    assert claims[0].fact_ids == [fact.id]
    assert claims[0].source_ids == fact.source_ids
    assert "llm_generation_failed" in claims[0].reason_codes


def test_explanation_uses_natural_wording_for_observation_period(monkeypatch):
    fact = Fact(
        id="F1", kind="diagnosis",
        text_en="The patient's condition improved during the observation period.",
        source_ids=["S1"],
    )
    monkeypatch.setattr(
        explain,
        "chat_completion",
        lambda **_kwargs: SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(
                content="The patient's condition got better during the time they were being watched."
            ))]
        ),
    )

    result = explain.generate_explanation(fact)

    assert result == "The patient's condition got better during the time they were monitored."
