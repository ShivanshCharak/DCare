import asyncio
import json
import pytest
from fastapi import HTTPException

from starlette.requests import Request

from app import main
from app.models import Claim, State
from app.store import store


def setup_function():
    store.documents.clear()


def json_request(payload: dict) -> Request:
    body = json.dumps(payload).encode("utf-8")
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/documents",
        "headers": [(b"content-type", b"application/json")],
        "query_string": b"",
        "server": ("test", 80),
        "client": ("test", 1234),
        "scheme": "http",
        "http_version": "1.1",
    }
    return Request(scope, receive)


def multipart_file_request(filename: str, content: bytes) -> Request:
    boundary = "synthetic-test-boundary"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        "Content-Type: text/plain; charset=utf-8\r\n\r\n"
    ).encode("utf-8") + content + f"\r\n--{boundary}--\r\n".encode("utf-8")
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/documents",
        "headers": [
            (b"content-type", f"multipart/form-data; boundary={boundary}".encode()),
            (b"content-length", str(len(body)).encode()),
        ],
        "query_string": b"",
        "server": ("test", 80),
        "client": ("test", 1234),
        "scheme": "http",
        "http_version": "1.1",
    }
    return Request(scope, receive)


def test_text_file_upload_handler_extracts_source_sentences(monkeypatch):
    monkeypatch.setattr(main.settings, "fact_extraction_mode", "deterministic")
    async def upload():
        request = multipart_file_request(
            "synthetic-summary.txt",
            b"Diagnosis:\nA synthetic diagnosis was recorded.",
        )
        form = await request.form()
        return await main.create_document(request, file=form["file"])

    document = asyncio.run(upload())
    assert document.source_name == "synthetic-summary.txt"
    assert document.facts[0].kind == "diagnosis"
    assert document.facts[0].source_ids == ["S1"]


def test_structured_extraction_error_is_returned_without_fallback(monkeypatch):
    monkeypatch.setattr(main.settings, "fact_extraction_mode", "structured_llm")
    monkeypatch.setattr(
        main,
        "extract_facts",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("source validation failed")),
    )
    with pytest.raises(HTTPException) as raised:
        asyncio.run(main.create_document(json_request({"text": "Diagnosis:\nPneumonia."})))
    assert raised.value.status_code == 502
    assert raised.value.detail["code"] == "fact_extraction_failed"
    assert "source validation failed" in raised.value.detail["message"]
    assert len(store.documents) == 0


def test_upload_with_sentences_but_no_supported_facts_enters_source_review_queue(monkeypatch):
    monkeypatch.setattr(main.settings, "fact_extraction_mode", "deterministic")
    document = asyncio.run(main.create_document(json_request({"text": "Unrecognized heading:\nAdditional details were documented."})))
    assert document.facts == []
    item = next(
        item for item in main.review_queue()
        if item.document_id == document.id and item.source_sentence
        and item.source_sentence.text == "Additional details were documented."
    )
    assert item.item_type == "source_sentence"
    assert item.source_sentence.text == "Additional details were documented."


def test_upload_explain_questions_and_review_handler_flow(monkeypatch):
    monkeypatch.setattr(main.settings, "fact_extraction_mode", "deterministic")
    document = asyncio.run(
        main.create_document(
            json_request(
                {
                    "text": "Medications:\nTake amlodipine 5 mg once daily.",
                    "source_name": "synthetic-handler-test",
                }
            )
        )
    )
    assert document.status == "extracted"
    assert len(document.facts) == 1
    assert document.facts[0].source_ids == [document.sentences[0].id]

    def fake_explain(facts):
        return [
            Claim(
                id="C1",
                text=facts[0].text_en,
                language="en",
                fact_ids=[facts[0].id],
                source_ids=facts[0].source_ids,
                state=State.NEEDS_CLINICIAN,
                reason_codes=["synthetic_test_claim"],
            )
        ]

    monkeypatch.setattr(main, "explain_facts", fake_explain)
    explained = main.explain_document(document.id, lang="en")
    assert explained.document.status == "explained"
    assert explained.document.claims[0].source_ids == [document.sentences[0].id]
    assert explained.document.claims[0].id == f"{document.id}-C1"
    assert isinstance(explained.doctor_questions, list)
    assert any(item.claim.id == f"{document.id}-C1" for item in main.review_queue())

    reviewed = main.review_claim(
        f"{document.id}-C1",
        main.ClaimReviewRequest(action="approve", reviewer="handler-test"),
    )
    assert reviewed.recorded is True
    assert reviewed.state == State.REVIEW_SUGGESTED
    assert main.review_queue() == []
