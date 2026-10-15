import pytest

from app.models import DocumentRecord, Sentence
from app.store import SQLiteDocumentMapping


def test_document_store_survives_reopen(tmp_path):
    database_path = tmp_path / "documents.sqlite3"
    database_url = f"sqlite:///{database_path}"
    original = DocumentRecord(
        id="D1",
        source_name="synthetic-persistence-test",
        original_text="A synthetic diagnosis was recorded.",
        sentences=[
            Sentence(
                id="S1",
                text="A synthetic diagnosis was recorded.",
                section="diagnosis",
            )
        ],
        status="extracted",
    )

    first_store = SQLiteDocumentMapping(database_url)
    first_store[original.id] = original
    first_store.close()

    reopened_store = SQLiteDocumentMapping(database_url)
    restored = reopened_store["D1"]
    assert restored == original
    assert list(reopened_store) == ["D1"]
    reopened_store.close()


def test_document_store_requires_matching_key_and_id(tmp_path):
    mapping = SQLiteDocumentMapping(f"sqlite:///{tmp_path / 'documents.sqlite3'}")
    document = DocumentRecord(
        id="D1",
        source_name="synthetic",
        original_text="",
        sentences=[],
    )

    with pytest.raises(ValueError, match="must match"):
        mapping["D2"] = document
    mapping.close()
