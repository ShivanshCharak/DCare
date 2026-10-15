import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from bench import smoke_test


def test_ollama_smoke_test_lists_model_and_requests_completion(monkeypatch):
    calls = {}

    class FakeResponse:
        def __init__(self, data):
            self.data = data

        def raise_for_status(self):
            return None

        def json(self):
            return self.data

    def fake_get(url, **kwargs):
        calls["models_url"] = url
        return FakeResponse({"models": [{"name": "test-model"}]})

    def fake_post(url, **kwargs):
        calls["completion_url"] = url
        calls["completion"] = kwargs["json"]
        return FakeResponse({"message": {"content": "OK"}})

    monkeypatch.setattr(smoke_test.httpx, "get", fake_get)
    monkeypatch.setattr(smoke_test.httpx, "post", fake_post)
    result = smoke_test.run_smoke_test("http://localhost:11434/v1", "", "test-model")

    assert calls["models_url"].endswith("/api/tags")
    assert calls["completion_url"].endswith("/api/chat")
    assert calls["completion"]["think"] is False
    assert result["completion_request_succeeded"] is True


def test_ollama_smoke_test_rejects_model_not_served(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"models": [{"name": "other-model"}]}

    monkeypatch.setattr(smoke_test.httpx, "get", lambda *args, **kwargs: FakeResponse())
    with pytest.raises(ValueError, match="model ID"):
        smoke_test.run_smoke_test("http://localhost:11434/v1", "", "test-model")
