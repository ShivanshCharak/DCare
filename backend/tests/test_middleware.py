import asyncio
import json

from app.middleware import MaxRequestBodySize


def run_middleware(scope, incoming_messages, max_bytes=5):
    received = iter(incoming_messages)
    sent = []

    async def receive():
        return next(received)

    async def send(message):
        sent.append(message)

    async def app(scope, receive, send):
        while True:
            message = await receive()
            if not message.get("more_body", False):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    asyncio.run(MaxRequestBodySize(app, max_bytes)(scope, receive, send))
    return sent


def test_rejects_declared_oversized_request_body():
    sent = run_middleware(
        {"type": "http", "headers": [(b"content-length", b"6")]},
        [],
    )
    assert sent[0]["status"] == 413
    assert json.loads(sent[1]["body"])["detail"] == "Request body exceeds 5 bytes."


def test_rejects_chunked_body_that_exceeds_limit():
    sent = run_middleware(
        {"type": "http", "headers": []},
        [
            {"type": "http.request", "body": b"123", "more_body": True},
            {"type": "http.request", "body": b"456", "more_body": False},
        ],
    )
    assert sent[0]["status"] == 413


def test_allows_body_within_limit():
    sent = run_middleware(
        {"type": "http", "headers": []},
        [{"type": "http.request", "body": b"12345", "more_body": False}],
    )
    assert sent[0]["status"] == 200
    assert sent[1]["body"] == b"ok"

