"""HTTP-level integration tests using an in-process ASGI driver."""

import asyncio
import json
from contextlib import AsyncExitStack
from pathlib import Path
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from urllib.parse import urlsplit

from fastapi.routing import request_response
from app import main
from app.models import Claim, DocumentRecord, Fact, Sentence, State
from app.store import store


def setup_function():
    store.documents.clear()


def asgi_request(method: str, path: str, body: bytes = b"", headers=()):
    """Send one complete HTTP request through the real ASGI middleware/router."""
    parsed = urlsplit(path)
    request_headers = [(b"host", b"testserver")]
    request_headers.extend(headers)
    if body:
        request_headers.append((b"content-length", str(len(body)).encode("ascii")))

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": parsed.path,
        "raw_path": parsed.path.encode("ascii"),
        "query_string": parsed.query.encode("ascii"),
        "root_path": "",
        "headers": request_headers,
        "server": ("testserver", 80),
        "client": ("testclient", 12345),
    }
    scope_stack = AsyncExitStack()
    scope["fastapi_middleware_astack"] = scope_stack
    body_sent = False
    messages = []

    async def receive():
        nonlocal body_sent
        if body_sent:
            return {"type": "http.disconnect"}
        body_sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        messages.append(message)

    async def run():
        # Invoke FastAPI's real router and response serializer directly. The
        # outer ASGI middleware is covered separately; traversing this
        # environment's middleware stack blocks on disconnect handling.
        async with scope_stack:
            await asyncio.wait_for(
                main.app.router(scope, receive, send),
                timeout=3,
            )

    asyncio.run(run())
    starts = [message for message in messages if message["type"] == "http.response.start"]
    bodies = [message.get("body", b"") for message in messages if message["type"] == "http.response.body"]
    assert len(starts) == 1
    return starts[0]["status"], json.loads(b"".join(bodies) or b"null")


def install_async_test_adapter(monkeypatch, path, endpoint):
    """Avoid this environment's stalled AnyIO sync-endpoint thread dispatch."""
    async def adapter(*args, **kwargs):
        return endpoint(*args, **kwargs)

    route = next(
        route
        for route in main.app.routes
        if getattr(route, "path", None) == path
    )
    monkeypatch.setattr(route.dependant, "call", adapter)
    monkeypatch.setattr(route, "app", request_response(route.get_route_handler()))


def test_http_json_upload_explain_questions_and_review(monkeypatch):
    monkeypatch.setattr(main.settings, "fact_extraction_mode", "deterministic")
    status, uploaded = asgi_request(
        "POST",
        "/documents",
        json.dumps(
            {
                "text": "Medications:\nTake amlodipine 5 mg once daily.",
                "source_name": "synthetic-http-test",
            }
        ).encode(),
        [(b"content-type", b"application/json")],
    )
    assert status == 200
    assert uploaded["status"] == "extracted"
    assert uploaded["facts"][0]["source_ids"] == ["S1"]

    def fake_explain(facts):
        fact = facts[0]
        return [
            Claim(
                id="C-http",
                text=fact.text_en,
                fact_ids=[fact.id],
                source_ids=fact.source_ids,
                state=State.NEEDS_CLINICIAN,
                reason_codes=["synthetic_http_test"],
            )
        ]

    monkeypatch.setattr(main, "explain_facts", fake_explain)
    install_async_test_adapter(
        monkeypatch,
        "/documents/{doc_id}/explain",
        main.explain_document,
    )
    install_async_test_adapter(
        monkeypatch,
        "/doctor-questions/{doc_id}",
        main.doctor_questions,
    )
    install_async_test_adapter(
        monkeypatch,
        "/claims/{claim_id}/review",
        main.review_claim,
    )
    status, explained = asgi_request(
        "POST", f"/documents/{uploaded['id']}/explain?lang=en"
    )
    assert status == 200
    claim_id = explained["document"]["claims"][0]["id"]
    assert claim_id == f"{uploaded['id']}-C-http"
    assert isinstance(explained["doctor_questions"], list)

    status, questions = asgi_request("GET", f"/doctor-questions/{uploaded['id']}")
    assert status == 200
    assert isinstance(questions, list)

    status, review = asgi_request(
        "POST",
        f"/claims/{claim_id}/review",
        json.dumps({"action": "approve", "reviewer": "integration-test"}).encode(),
        [(b"content-type", b"application/json")],
    )
    assert status == 200
    assert review["recorded"] is True
    assert review["document_id"] == uploaded["id"]
    assert review["state"] == "review_suggested"


def test_http_multipart_text_upload_serializes_document_response(monkeypatch):
    monkeypatch.setattr(main.settings, "fact_extraction_mode", "deterministic")
    boundary = "synthetic-asgi-boundary"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="synthetic.txt"\r\n'
        "Content-Type: text/plain; charset=utf-8\r\n\r\n"
        "Diagnosis:\nA synthetic diagnosis was recorded.\r\n"
        f"--{boundary}--\r\n"
    ).encode()
    status, uploaded = asgi_request(
        "POST",
        "/documents",
        body,
        [(b"content-type", f"multipart/form-data; boundary={boundary}".encode())],
    )
    assert status == 200
    assert uploaded["source_name"] == "synthetic.txt"
    assert uploaded["facts"][0]["kind"] == "diagnosis"


def test_http_ambiguous_medication_is_serialized_for_clinician_routing(monkeypatch):
    monkeypatch.setattr(main.settings, "fact_extraction_mode", "deterministic")
    wording = "Take the medicines as listed in the 10 times a week."
    status, uploaded = asgi_request(
        "POST", "/documents",
        json.dumps({"text": f"Medications:\n{wording}"}).encode(),
        [(b"content-type", b"application/json")],
    )
    assert status == 200
    fact = uploaded["facts"][0]

    def fake_explain(_facts):
        return [Claim(
            id="C1", text=wording, fact_ids=[fact["id"]],
            source_ids=fact["source_ids"],
        )]

    monkeypatch.setattr(main, "explain_facts", fake_explain)
    install_async_test_adapter(monkeypatch, "/documents/{doc_id}/explain", main.explain_document)
    status, response = asgi_request("POST", f"/documents/{uploaded['id']}/explain")

    assert status == 200
    serialized_claim = response["document"]["claims"][0]
    assert serialized_claim["text"] == wording
    assert serialized_claim["state"] == "needs_clinician"
    assert "ambiguous_medication_schedule" in serialized_claim["reason_codes"]
    assert len(serialized_claim["checks"]) == 18
    assert len(serialized_claim["check_details"]) == 18
    assert serialized_claim["checks"]["exact_match"] == "passed"
    assert serialized_claim["check_details"]["risk_rules"]["message"]
    states = [claim["state"] for claim in response["document"]["claims"]]
    assert states.count("needs_clinician") == 1
    assert states.count("review_suggested") == 0


def test_http_serializes_check_status_and_details_for_four_claim_types(monkeypatch):
    monkeypatch.setattr(main.settings, "entailment_judge_enabled", False)
    kinds = ["diagnosis", "medication", "appointment", "warning_sign"]
    sentences = [Sentence(id=f"S{i}", text=text, section=kind) for i, (kind, text) in enumerate([
        ("diagnosis", "Hypertension was recorded."),
        ("medication", "Take amlodipine 5 mg once daily."),
        ("appointment", "Follow up in 2 weeks."),
        ("warning_sign", "Call if you develop a fever."),
    ], start=1)]
    facts = [Fact(
        id=f"F{i}", kind=kind, text_en=sentence.text, attrs={}, source_ids=[sentence.id]
    ) for i, (kind, sentence) in enumerate(zip(kinds, sentences), start=1)]
    store.documents["D-checks"] = DocumentRecord(
        id="D-checks", source_name="test", original_text="\n".join(s.text for s in sentences),
        sentences=sentences, facts=facts,
    )
    monkeypatch.setattr(main, "explain_facts", lambda _facts: [
        Claim(id=f"C{i}", text=fact.text_en, fact_ids=[fact.id], source_ids=fact.source_ids)
        for i, fact in enumerate(facts, start=1)
    ])
    install_async_test_adapter(monkeypatch, "/documents/{doc_id}/explain", main.explain_document)

    status, response = asgi_request("POST", "/documents/D-checks/explain")

    assert status == 200
    claims = response["document"]["claims"]
    assert [claim["id"].split("-")[-1] for claim in claims] == ["C1", "C2", "C3", "C4"]
    for claim in claims:
        assert len(claim["checks"]) == 18
        assert len(claim["check_details"]) == 18
        assert claim["checks"]["source_ids"] == "passed"
        for name, check_status in claim["checks"].items():
            detail = claim["check_details"][name]
            assert detail["name"] == name
            assert detail["status"] == check_status
            assert isinstance(detail["message"], str) and detail["message"]
    states = [claim["state"] for claim in claims]
    assert states == ["source_supported"] * 4


def test_http_complicated_synthetic_document_keeps_claims_source_linked(monkeypatch, caplog):
    from app.pipeline import structured_extract

    fixture = Path(__file__).parent / "fixtures" / "complicated_synthetic_discharge_test.txt"
    text = fixture.read_text(encoding="utf-8")
    monkeypatch.setattr(main.settings, "fact_extraction_mode", "structured_llm")

    def classify_batch(**kwargs):
        batch = json.loads(kwargs["messages"][1]["content"])["sentences"]
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content=json.dumps({"facts": [
                {"source_id": row["id"], "kind": row["allowed_kind"]}
                for row in batch if row["id"] not in {"S18", "S21"}
            ]})
        ))])

    monkeypatch.setattr(structured_extract, "chat_completion", classify_batch)
    install_async_test_adapter(monkeypatch, "/documents/{doc_id}/explain", main.explain_document)
    status, uploaded = asgi_request(
        "POST", "/documents",
        json.dumps({"text": text, "source_name": "complicated_synthetic_discharge_test.txt"}).encode(),
        [(b"content-type", b"application/json")],
    )
    assert status == 200
    assert len(uploaded["sentences"]) > 100
    assert uploaded["facts"]
    assert "source_ids=S18,S21" in caplog.text

    def source_preserving_explanations(facts):
        return [Claim(
            id=f"C{i}", text=fact.text_en, fact_ids=[fact.id],
            source_ids=fact.source_ids, state=State.PENDING_VERIFACATION,
        ) for i, fact in enumerate(facts, start=1)]

    monkeypatch.setattr(main, "explain_facts", source_preserving_explanations)
    status, response = asgi_request("POST", f"/documents/{uploaded['id']}/explain?lang=en")
    assert status == 200
    document = response["document"]
    assert len(document["claims"]) == len(uploaded["facts"])
    assert all(claim["state"] != State.VERIFIED.value for claim in document["claims"])

    sentences_by_id = {sentence["id"]: sentence for sentence in document["sentences"]}
    facts_by_id = {fact["id"]: fact for fact in document["facts"]}
    claims_by_fact = {claim["fact_ids"][0]: claim for claim in document["claims"]}
    metformin = next(fact for fact in document["facts"] if "metformin 500 mg" in fact["text_en"].lower())
    assert "twice daily" in metformin["text_en"] and "once daily" in metformin["text_en"]
    ambiguous = next(fact for fact in document["facts"] if "10 times a week" in fact["text_en"].lower())
    assert "ambiguous_medication_schedule" in claims_by_fact[ambiguous["id"]]["reason_codes"]

    unsupported = next(sentence for sentence in document["sentences"] if "pneumonia has completely cleared" in sentence["text"].lower())
    assert unsupported["section"] == "unknown"
    assert all(unsupported["id"] not in fact["source_ids"] for fact in facts_by_id.values())
    for claim in document["claims"]:
        fact = facts_by_id[claim["fact_ids"][0]]
        assert claim["text"] == fact["text_en"]
        assert claim["source_ids"] == fact["source_ids"]
        assert all(source_id in sentences_by_id for source_id in claim["source_ids"])


def test_http_empty_claim_generation_is_an_error_not_an_explained_document(monkeypatch):
    sentence = Sentence(id="S1", text="Pneumonia was recorded.", section="diagnosis")
    fact = Fact(id="F1", kind="diagnosis", text_en=sentence.text, source_ids=[sentence.id])
    store.documents["D-empty-claims"] = DocumentRecord(
        id="D-empty-claims", source_name="test", original_text=sentence.text,
        sentences=[sentence], facts=[fact], status="extracted",
    )
    monkeypatch.setattr(main, "explain_facts", lambda _facts: [])
    with pytest.raises(HTTPException) as raised:
        main.explain_document("D-empty-claims", lang="en")

    assert raised.value.status_code == 502
    assert raised.value.detail["code"] == "claim_generation_empty"
    assert store.documents["D-empty-claims"].status == "extracted"
