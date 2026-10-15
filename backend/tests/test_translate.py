import pytest
from fastapi import HTTPException

from app.main import explain_document
from app.models import DocumentRecord, Sentence
from app.store import store


@pytest.mark.parametrize("language", ["hi"])
def test_explain_rejects_documents_without_facts_before_translation(language: str):
    store.documents.clear()
    store.documents["D1"] = DocumentRecord(
        id="D1",
        source_name="synthetic-test",
        original_text="Diagnosis recorded.",
        sentences=[Sentence(id="S1", text="Diagnosis recorded.", section="diagnosis")],
        facts=[],
        claims=[],
        status="extracted",
    )

    with pytest.raises(HTTPException) as error:
        explain_document("D1", lang=language)

    assert error.value.status_code == 422
    assert error.value.detail["code"] == "no_extractable_facts"
