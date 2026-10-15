import pytest

from app.models import Sentence
from app.pipeline.extract import (
    extract_facts,
    validate_fact_sources,
)


def test_extracts_facts_from_recognized_sections():
    sentences = [
        Sentence(
            id="S1",
            text="Hypertension",
            section="diagnosis",
        ),
        Sentence(
            id="S2",
            text="Amlodipine 5 mg once daily.",
            section="medications",
        ),
        Sentence(
            id="S3",
            text="Visit the clinic in 7 days.",
            section="follow_up",
        ),
        Sentence(
            id="S4",
            text="Seek medical attention for chest pain.",
            section="warning_signs",
        ),
    ]

    facts = extract_facts(sentences)

    assert len(facts) == 4

    assert facts[0].kind == "diagnosis"
    assert facts[0].source_ids == ["S1"]

    assert facts[1].kind == "medication"
    assert facts[1].attrs["dose"] == "5 mg"
    assert facts[1].attrs["frequency"] == "once daily"
    assert facts[1].source_ids == ["S2"]

    assert facts[2].kind == "appointment"
    assert facts[2].source_ids == ["S3"]

    assert facts[3].kind == "warning_sign"
    assert facts[3].source_ids == ["S4"]


def test_ignores_unknown_sections():
    sentences = [
        Sentence(
            id="S1",
            text="Some sentence with an unknown classification.",
            section="unknown",
        )
    ]

    assert extract_facts(sentences) == []


def test_does_not_extract_empty_sentences():
    sentences = [
        Sentence(
            id="S1",
            text="   ",
            section="diagnosis",
        )
    ]

    assert extract_facts(sentences) == []


def test_removes_duplicate_facts():
    sentences = [
        Sentence(
            id="S1",
            text="Hypertension",
            section="diagnosis",
        ),
        Sentence(
            id="S2",
            text="Hypertension",
            section="diagnosis",
        ),
    ]

    facts = extract_facts(sentences)

    assert len(facts) == 1
    assert facts[0].source_ids == ["S1"]


def test_validates_source_sentence_ids():
    sentences = [
        Sentence(
            id="S1",
            text="Hypertension",
            section="diagnosis",
        )
    ]

    facts = extract_facts(sentences)

    validated = validate_fact_sources(facts, sentences)

    assert validated == facts


def test_rejects_invalid_source_sentence_ids():
    sentences = [
        Sentence(
            id="S1",
            text="Hypertension",
            section="diagnosis",
        )
    ]

    facts = extract_facts(sentences)

    # Simulate a faulty extractor referencing a nonexistent sentence.
    facts[0].source_ids = ["S999"]

    with pytest.raises(ValueError, match="unknown sentence IDs"):
        validate_fact_sources(facts, sentences)


def test_rejects_facts_without_source_ids():
    sentences = [
        Sentence(
            id="S1",
            text="Hypertension",
            section="diagnosis",
        )
    ]

    facts = extract_facts(sentences)
    facts[0].source_ids = []

    with pytest.raises(ValueError, match="no source sentence IDs"):
        validate_fact_sources(facts, sentences)


def test_rejects_fact_that_changes_source_wording_or_kind():
    sentence = Sentence(
        id="S1", text="Take amlodipine 5 mg once daily.", section="medications"
    )
    facts = extract_facts([sentence])
    facts[0].text_en = "Take amlodipine once daily."
    with pytest.raises(ValueError, match="does not preserve source sentence"):
        validate_fact_sources(facts, [sentence])

    facts = extract_facts([sentence])
    facts[0].kind = "diagnosis"
    with pytest.raises(ValueError, match="conflicts with source"):
        validate_fact_sources(facts, [sentence])
