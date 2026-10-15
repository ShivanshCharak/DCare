import pytest
from fastapi import HTTPException

from app.main import explain_document
from app.models import DocumentRecord, Sentence
from app.pipeline import translate
from app import llm_client
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


@pytest.mark.parametrize("language", ["hi", "bn", "gu", "kn", "ml", "mr", "or", "pa", "ta", "te"])
def test_translation_generation_always_uses_sarvam(language: str, monkeypatch):
    captured = []

    def fake_completion(**kwargs):
        captured.append(kwargs)
        return translate.TRANSLATION_EXAMPLES[language]

    monkeypatch.setattr(translate, "text_completion", fake_completion)
    assert translate._translate_text("Take one tablet daily.", language) == translate.TRANSLATION_EXAMPLES[language]
    assert captured[0]["model"] == "mashriram/sarvam-1"
    assert translate.LANGUAGES[language] in captured[0]["prompt"]


def test_back_translation_always_uses_sarvam(monkeypatch):
    captured = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return "Take one tablet daily."

    monkeypatch.setattr(translate, "text_completion", fake_completion)
    assert translate._back_translate("...", "mr") == "Take one tablet daily."
    assert captured["model"] == "mashriram/sarvam-1"
    assert "Marathi" in captured["prompt"]


def test_translation_rejects_english_fallback_for_hindi(monkeypatch):
    monkeypatch.setattr(translate, "text_completion", lambda **kwargs: "Take one tablet daily.")
    with pytest.raises(ValueError, match="no Hindi script text"):
        translate._translate_text("Take one tablet daily.", "hi")


def test_text_completion_uses_ollama_raw_generate_endpoint(monkeypatch):
    captured = {}

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"response": "translated"}

    def fake_post(url, *, json, timeout):
        captured.update(url=url, payload=json, timeout=timeout)
        return Response()

    monkeypatch.setattr(llm_client.settings, "llm_base_url", "http://localhost:11434/v1")
    monkeypatch.setattr(llm_client.httpx, "post", fake_post)
    assert llm_client.text_completion(model="mashriram/sarvam-1", prompt="prompt") == "translated"
    assert captured["url"] == "http://localhost:11434/api/generate"
    assert captured["payload"]["raw"] is True
    assert captured["payload"]["stream"] is False
