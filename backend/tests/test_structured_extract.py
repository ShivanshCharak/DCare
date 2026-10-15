import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.models import Claim, Sentence, State
from app.pipeline import structured_extract
from app.pipeline.structured_extract import (
    FactSelectionResponse,
    extract_facts_structured,
    extract_facts_with_fallback,
)
from app.pipeline.verify import verify_claims


def test_schema_rejects_model_authored_fact_text_and_unknown_fields():
    with pytest.raises(ValidationError):
        FactSelectionResponse.model_validate_json(
            '{"facts":[{"source_id":"S1","kind":"medication",'
            '"text_en":"Take a new drug."}]}'
        )


def test_structured_extraction_copies_source_sentence_and_validates_ids(monkeypatch):
    sentence = Sentence(
        id="S1",
        text="Take amlodipine 5 mg once daily in the evening for 5 days.",
        section="medications",
    )
    captured = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content='{"facts":[{"source_id":"S1","kind":"medication"}]}'
                    )
                )
            ]
        )

    monkeypatch.setattr(structured_extract, "chat_completion", fake_completion)
    facts = extract_facts_structured([sentence])

    assert captured["response_format"]["type"] == "json_schema"
    assert facts[0].text_en == sentence.text
    assert facts[0].source_ids == ["S1"]
    assert facts[0].attrs == {
        "dose": "5 mg",
        "frequency": "once daily",
        "duration": "for 5 days",
        "timing": "in the evening",
        "extraction_mode": "structured_llm",
    }
    claim = Claim(
        id="C1",
        text=sentence.text,
        fact_ids=[facts[0].id],
        source_ids=facts[0].source_ids,
    )
    verified = verify_claims([claim], [sentence], facts)[0]
    assert verified.checks["fact_extraction"] == "passed"
    assert "structured_extraction_requires_review" not in verified.reason_codes
    assert verified.state == State.SOURCE_SUPPORTED


def test_invalid_source_reference_is_not_hidden_by_deterministic_fallback(monkeypatch):
    sentences = [
        Sentence(id="S1", text="Pneumonia was diagnosed.", section="diagnosis")
    ]

    def invalid_model_result(_sentences):
        raise ValueError("unknown sentence id")

    monkeypatch.setattr(
        structured_extract, "extract_facts_structured", invalid_model_result
    )
    with pytest.raises(ValueError, match="unknown sentence id"):
        extract_facts_with_fallback(sentences, mode="structured_llm")


def test_structured_kind_conflicting_with_heading_is_rejected(monkeypatch):
    sentence = Sentence(id="S1", text="Take amlodipine.", section="medications")

    def fake_completion(**kwargs):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content='{"facts":[{"source_id":"S1","kind":"diagnosis"}]}'
                    )
                )
            ]
        )

    monkeypatch.setattr(structured_extract, "chat_completion", fake_completion)
    with pytest.raises(ValueError, match="conflicts with its source section"):
        extract_facts_with_fallback([sentence], mode="structured_llm")


def test_deterministic_mode_does_not_call_model(monkeypatch):
    sentences = [
        Sentence(id="S1", text="Pneumonia was diagnosed.", section="diagnosis")
    ]

    def unexpected_model_call(_sentences):
        raise AssertionError("model should not be called in deterministic mode")

    monkeypatch.setattr(
        structured_extract, "extract_facts_structured", unexpected_model_call
    )
    assert len(extract_facts_with_fallback(sentences, mode="deterministic")) == 1


def test_structured_extraction_logs_but_preserves_nonfact_source_sentences(monkeypatch, caplog):
    sentences = [
        Sentence(id="S1", text="Pneumonia was diagnosed.", section="diagnosis"),
        Sentence(id="S2", text="Do not rewrite pending as negative.", section="diagnosis"),
    ]

    def classify_facts_only(**kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(
                content='{"facts":[{"source_id":"S1","kind":"diagnosis"}]}'
            ))]
        )

    monkeypatch.setattr(structured_extract, "chat_completion", classify_facts_only)
    facts = extract_facts_structured(sentences)

    assert [fact.source_ids for fact in facts] == [["S1"]]
    assert sentences[1].id == "S2" and sentences[1].text == "Do not rewrite pending as negative."
    assert "omitted_count=1 source_ids=S2" in caplog.text


def test_structured_extraction_keeps_duplicate_sentences_with_both_sources(monkeypatch):
    sentences = [
        Sentence(id="S1", text="Hypertension was diagnosed.", section="diagnosis"),
        Sentence(id="S2", text="Hypertension was diagnosed.", section="diagnosis"),
    ]

    def fake_completion(**kwargs):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content='{"facts":[{"source_id":"S1","kind":"diagnosis"},'
            '{"source_id":"S2","kind":"diagnosis"}]}'
        ))])

    monkeypatch.setattr(structured_extract, "chat_completion", fake_completion)
    facts = extract_facts_structured(sentences)
    assert [fact.source_ids for fact in facts] == [["S1"], ["S2"]]


def test_structured_extraction_batches_long_documents_without_losing_source_ids(monkeypatch):
    sentences = [
        Sentence(id=f"S{i}", text=f"Discharge instruction number {i}.", section="medications")
        for i in range(1, 28)
    ]
    batch_ids = []

    def fake_completion(**kwargs):
        payload = json.loads(kwargs["messages"][1]["content"])
        ids = [sentence["id"] for sentence in payload["sentences"]]
        batch_ids.append(ids)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content=json.dumps({"facts": [
                {"source_id": source_id, "kind": "medication"} for source_id in ids
            ]})
        ))])

    monkeypatch.setattr(structured_extract, "chat_completion", fake_completion)
    facts = extract_facts_structured(sentences)

    assert [len(ids) for ids in batch_ids] == [12, 12, 3]
    assert [fact.source_ids for fact in facts] == [[sentence.id] for sentence in sentences]
    assert [fact.id for fact in facts] == [f"F{i}" for i in range(1, 28)]


def test_structured_extraction_preserves_medication_source_verbatim(monkeypatch):
    sentence = Sentence(
        id="S1",
        text="Take warfarin 5 mg 10 times a day in the evening for 5 days.",
        section="medications",
    )

    def fake_completion(**kwargs):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content='{"facts":[{"source_id":"S1","kind":"medication"}]}'
        ))])

    monkeypatch.setattr(structured_extract, "chat_completion", fake_completion)
    fact = extract_facts_structured([sentence])[0]
    assert fact.text_en == sentence.text
    assert fact.source_ids == ["S1"]
    assert fact.attrs["dose"] == "5 mg"
    assert fact.attrs["frequency"] == "10 times a day"
    assert fact.attrs["duration"] == "for 5 days"
    assert fact.attrs["timing"] == "in the evening"
