import asyncio
import json

from app.middleware import BearerTokenAuth, MaxRequestBodySize


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


def run_auth(headers=None, *, token="", app_env="development", path="/review-queue"):
    sent = []

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "path": path, "headers": headers or []}
    asyncio.run(BearerTokenAuth(app, token, app_env)(scope, receive, send))
    return sent


def test_bearer_auth_rejects_missing_or_invalid_tokens():
    for headers in ([], [(b"authorization", b"Bearer wrong-token")]):
        sent = run_auth(headers, token="expected-token")
        assert sent[0]["status"] == 401
        assert (b"www-authenticate", b"Bearer") in sent[0]["headers"]


def test_bearer_auth_accepts_configured_token():
    sent = run_auth(
        [(b"authorization", b"Bearer expected-token")],
        token="expected-token",
    )
    assert sent[0]["status"] == 204


def test_bearer_auth_is_optional_in_development_and_health_is_public():
    assert run_auth()[0]["status"] == 204
    assert run_auth(token="expected-token", path="/health")[0]["status"] == 204


def test_production_requires_configured_token():
    sent = run_auth(app_env="production")
    assert sent[0]["status"] == 503
