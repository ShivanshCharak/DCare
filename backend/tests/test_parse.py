from pathlib import Path

from app.pipeline.parse import parse_and_split


def test_document_footer_is_not_parsed_as_a_sentence():
    text = """\
WARNING SIGNS
Seek urgent medical care if you experience difficulty breathing.
END OF SYNTHETIC DISCHARGE SUMMARY
"""

    sentences = parse_and_split(text)
    sentence_texts = [sentence.text for sentence in sentences]

    assert (
        "Seek urgent medical care if you experience difficulty breathing."
        in sentence_texts
    )
    assert "END OF SYNTHETIC DISCHARGE SUMMARY" not in sentence_texts


def test_document_footer_does_not_become_a_warning_sign_fact():
    from app.pipeline.extract import extract_facts

    text = """\
WARNING SIGNS
Seek urgent medical care if you experience difficulty breathing.
END OF SYNTHETIC DISCHARGE SUMMARY
"""

    sentences = parse_and_split(text)
    facts = extract_facts(sentences)

    assert len(facts) == 1
    assert facts[0].kind == "warning_sign"
    assert (
        facts[0].text_en
        == "Seek urgent medical care if you experience difficulty breathing."
    )


def test_ordinary_sentence_containing_end_is_preserved():
    text = """\
WARNING SIGNS
Contact a healthcare professional if your symptoms do not improve.
"""

    sentences = parse_and_split(text)

    assert len(sentences) == 1
    assert sentences[0].text == (
        "Contact a healthcare professional if your symptoms do not improve."
    )
    assert sentences[0].section == "warning_signs"


def test_alternate_narrative_headings_keep_facts_in_supported_sections():
    from app.pipeline.extract import extract_facts

    text = """\
Clinical diagnosis:
A synthetic condition was recorded.
Medication list:
Follow the printed medication instructions for amlodipine.
Follow-up plan:
A follow-up appointment is set for 7 days after discharge.
Activity limits:
Do not lift objects heavier than 5 kg until the follow-up visit.
When to get help:
Seek urgent help if difficulty breathing occurs.
Results pending:
The final laboratory report is pending.
"""
    sentences = parse_and_split(text)
    facts = extract_facts(sentences)

    assert [fact.kind for fact in facts] == [
        "diagnosis",
        "medication",
        "appointment",
        "restriction",
        "warning_sign",
        "pending_test",
    ]
    assert all(fact.source_ids == [sentence.id] for fact, sentence in zip(facts, sentences))


def test_numbered_sections_extract_fixture_facts_without_claiming_unknown_sections():
    from app.pipeline.extract import extract_facts

    fixture = Path(__file__).parent / "fixtures" / "complicated_synthetic_discharge_test.txt"
    text = fixture.read_text(encoding="utf-8")
    sentences = parse_and_split(text)
    facts = extract_facts(sentences, mode="deterministic")
    sentences_by_id = {sentence.id: sentence for sentence in sentences}

    assert len(sentences) > 100
    assert {"diagnosis", "medications", "follow_up", "restrictions", "warning_signs"}.issubset(
        {sentence.section for sentence in sentences}
    )
    assert facts
    assert all(source_id in sentences_by_id for fact in facts for source_id in fact.source_ids)

    metformin_fact = next(fact for fact in facts if "metformin 500 mg" in fact.text_en.lower())
    assert "twice daily" in metformin_fact.text_en
    assert "once daily" in metformin_fact.text_en
    assert any("10 times a week" in fact.text_en for fact in facts)
    # The draft assertion appears in an unrecognized test section, so it stays
    # in the source record but is never promoted to a discharge fact.
    unsupported = next(sentence for sentence in sentences if "pneumonia has completely cleared" in sentence.text.lower())
    assert unsupported.section == "unknown"
    assert all(unsupported.id not in fact.source_ids for fact in facts)
