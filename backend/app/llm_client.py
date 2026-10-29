"""Ollama and OpenAI-compatible client supporting local and free hosted inference."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from ipaddress import ip_address
from urllib.parse import urlparse

import httpx

from .config import settings


def _validated_base_url() -> str:
    base_url = settings.llm_base_url.rstrip("/")

    # If using OpenAI-compatible or remote LLM is explicitly allowed, allow remote endpoints
    if settings.llm_provider == "openai_compatible" or settings.allow_remote_llm:
        return base_url

    hostname = urlparse(base_url).hostname
    local_aliases = {"localhost", "host.docker.internal", "host.containers.internal"}
    try:
        local_address = bool(hostname) and (
            ip_address(hostname).is_private
            or ip_address(hostname).is_loopback
            or ip_address(hostname).is_link_local
        )
    except ValueError:
        local_address = hostname in local_aliases
    if not local_address:
        raise ValueError(
            "Model endpoint must resolve to a local or private-network host when using local Ollama. "
            "Set ALLOW_REMOTE_LLM=true or LLM_PROVIDER=openai_compatible to allow remote endpoints."
        )
    return base_url


def chat_completion(
    *,
    model: str,
    messages: list[dict[str, str]],
    temperature: float = 0,
    response_format: dict[str, Any] | None = None,
    timeout: float = 60.0,
) -> SimpleNamespace:
    """Call either OpenAI-compatible hosted API or native Ollama API."""
    base_url = _validated_base_url()

    # Provider: OpenAI-compatible (Groq, Together, Hugging Face, OpenRouter, etc.)
    if settings.llm_provider == "openai_compatible":
        endpoint = base_url if base_url.endswith("/chat/completions") else f"{base_url}/chat/completions"
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if settings.llm_api_key:
            headers["Authorization"] = f"Bearer {settings.llm_api_key}"

        messages_to_send = [dict(m) for m in messages]
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages_to_send,
            "temperature": temperature,
        }
        if response_format:
            payload["response_format"] = {"type": "json_object"}
            has_json_word = any("json" in m.get("content", "").lower() for m in messages_to_send)
            if not has_json_word and messages_to_send:
                messages_to_send[0] = {
                    **messages_to_send[0],
                    "content": messages_to_send[0]["content"] + "\nReturn the response in valid JSON format.",
                }
                payload["messages"] = messages_to_send

        response = httpx.post(endpoint, headers=headers, json=payload, timeout=timeout)
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )

    # Provider: Ollama (default local)
    ollama_base = base_url[:-3] if base_url.endswith("/v1") else base_url
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "think": False,
        "stream": False,
        "options": {"temperature": temperature},
    }
    if response_format:
        schema = response_format.get("json_schema", {}).get("schema")
        if schema is None:
            raise ValueError("Ollama structured responses require a JSON Schema")
        payload["format"] = schema

    response = httpx.post(
        f"{ollama_base}/api/chat",
        json=payload,
        timeout=timeout,
    )
    response.raise_for_status()
    content = response.json().get("message", {}).get("content")
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def text_completion(
    *,
    model: str,
    prompt: str,
    temperature: float = 0,
    timeout: float = 60.0,
) -> str | None:
    """Call raw completion or chat fallback for completion models."""
    if settings.llm_provider == "openai_compatible" and model != "mashriram/sarvam-1":
        # Forward prompt to chat endpoint as a single prompt
        res = chat_completion(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            timeout=timeout,
        )
        return res.choices[0].message.content

    base_url = _validated_base_url()
    ollama_base = base_url[:-3] if base_url.endswith("/v1") else base_url
    response = httpx.post(
        f"{ollama_base}/api/generate",
        json={
            "model": model,
            "prompt": prompt,
            "raw": True,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": 512,
                "stop": ["\nEnglish:", "\n English:", "\n\n English:"],
            },
        },
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json().get("response")
