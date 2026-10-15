"""Small synchronous Ollama chat client for the local model integration."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from ipaddress import ip_address
from urllib.parse import urlparse

import httpx

from .config import settings


def chat_completion(
    *,
    model: str,
    messages: list[dict[str, str]],
    temperature: float = 0,
    response_format: dict[str, Any] | None = None,
    timeout: float = 60.0,
) -> SimpleNamespace:
    """Call Ollama's native API so thinking models can use ``think: false``."""
    base_url = settings.llm_base_url.rstrip("/")
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
        raise ValueError("Model endpoint must resolve to a local or private-network host; external endpoints are blocked to protect source text.")
    if base_url.endswith("/v1"):
        base_url = base_url[:-3]

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
        f"{base_url}/api/chat",
        json=payload,
        timeout=timeout,
    )
    response.raise_for_status()
    content = response.json().get("message", {}).get("content")
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )
