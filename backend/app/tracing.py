"""Langfuse v5 tracing integration for Discharge Explainer.

Uses the Langfuse Python SDK v5 (`get_client()` / context-manager API) to
create a properly-nested trace hierarchy for every document pipeline run:

    trace  discharge-explainer-pipeline   (root span, tagged per feature)
    ├── generation  fact-extraction        (when LLM-based extraction is used)
    ├── generation  explain-fact           (one per fact)
    ├── generation  verify-claim           (one per claim)
    ├── generation  translate-claim        (one per claim, when lang != "en")
    └── generation  chat_completion / text_completion  (raw LLM calls)

Raw LLM calls that happen *outside* a pipeline context are still captured as
standalone generations so no signal is lost.

Environment variables (standard Langfuse v5):
    LANGFUSE_PUBLIC_KEY   – pk-lf-…
    LANGFUSE_SECRET_KEY   – sk-lf-…
    LANGFUSE_BASE_URL     – https://cloud.langfuse.com  (or self-hosted URL)
    LANGFUSE_ENABLED      – "true" to activate (maps to settings.langfuse_enabled)

The existing config variables (LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY,
LANGFUSE_HOST) are kept in Settings for backwards-compat; this module reads
them via the `settings` object at init time and sets the OTEL env vars that
the Langfuse v5 SDK expects.
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Any, Generator, Optional

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Langfuse client initialisation (singleton via get_client())
# ---------------------------------------------------------------------------

_initialised: bool = False


def _ensure_env_vars() -> None:
    """Copy settings into the env vars that Langfuse v5 expects, if not already set."""
    if settings.langfuse_public_key and not os.environ.get("LANGFUSE_PUBLIC_KEY"):
        os.environ["LANGFUSE_PUBLIC_KEY"] = settings.langfuse_public_key
    if settings.langfuse_secret_key and not os.environ.get("LANGFUSE_SECRET_KEY"):
        os.environ["LANGFUSE_SECRET_KEY"] = settings.langfuse_secret_key
    # Prefer LANGFUSE_BASE_URL (v5 standard); fall back to legacy LANGFUSE_HOST
    base_url = getattr(settings, "langfuse_base_url", "") or settings.langfuse_host
    if base_url and not os.environ.get("LANGFUSE_BASE_URL"):
        os.environ["LANGFUSE_BASE_URL"] = base_url


def _get_client():
    """Return the Langfuse singleton client, or None when tracing is disabled."""
    global _initialised

    if not settings.langfuse_enabled:
        return None

    _ensure_env_vars()

    try:
        from langfuse import get_client  # type: ignore[import]

        client = get_client()
        if not _initialised:
            logger.info(
                "Langfuse observability initialised (v5) → %s",
                os.environ.get("LANGFUSE_BASE_URL", settings.langfuse_host),
            )
            _initialised = True
        return client
    except Exception as exc:
        logger.warning("Could not initialise Langfuse client: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Context-manager helpers for pipeline stages
# ---------------------------------------------------------------------------

@contextmanager
def pipeline_trace(
    doc_id: str,
    source_name: str,
    feature: str = "discharge-explainer",
) -> Generator[Any, None, None]:
    """Open a root span for one full pipeline run.

    Usage::

        with pipeline_trace(doc_id, source_name) as root:
            claims = explain_facts(facts)

    All child observations created inside (via `generation_span`) are
    automatically nested under this root via OpenTelemetry context propagation.
    """
    client = _get_client()
    if client is None:
        yield None
        return

    try:
        from langfuse import propagate_attributes  # type: ignore[import]

        with client.start_as_current_observation(
            as_type="span",
            name="discharge-explainer-pipeline",
            input={"doc_id": doc_id, "source_name": source_name},
            metadata={"feature": feature},
        ) as root_span:
            with propagate_attributes(tags=[feature]):
                try:
                    yield root_span
                    root_span.update(
                        output={"status": "completed"},
                    )
                except Exception as exc:
                    root_span.update(
                        output={"status": "error", "error": str(exc)},
                        level="ERROR",
                        status_message=str(exc),
                    )
                    raise
    except ImportError:
        yield None


@contextmanager
def generation_span(
    name: str,
    *,
    model: str,
    input_data: Any,
    metadata: Optional[dict[str, Any]] = None,
) -> Generator[Any, None, None]:
    """Open a *generation* observation for a single LLM call.

    The caller is responsible for calling ``.update(output=..., usage_details=...)``
    on the yielded object before the ``with`` block exits.

    Usage::

        with generation_span("explain-fact", model=model_id, input_data=messages) as gen:
            response = llm_call(...)
            gen.update(output=response.content, usage_details=usage)
    """
    client = _get_client()
    if client is None:
        yield None
        return

    try:
        with client.start_as_current_observation(
            as_type="generation",
            name=name,
            model=model,
            input=input_data,
            metadata=metadata or {},
        ) as gen:
            try:
                yield gen
            except Exception as exc:
                gen.update(
                    level="ERROR",
                    status_message=str(exc),
                )
                raise
    except Exception as exc:
        logger.debug("Langfuse generation span error (%s): %s", name, exc)
        yield None


# ---------------------------------------------------------------------------
# Standalone helper kept for backwards-compat with existing llm_client.py calls
# ---------------------------------------------------------------------------

def trace_generation(
    name: str,
    *,
    model: str,
    input_data: Any,
    output_data: Any,
    metadata: Optional[dict[str, Any]] = None,
    usage: Optional[dict[str, int]] = None,
    error: Optional[str] = None,
) -> None:
    """Record a completed LLM generation as a Langfuse observation.

    This function is called from llm_client.py after every LLM call.  When
    a ``pipeline_trace`` context is active the observation is automatically
    nested under it via OTel context propagation.  When called outside any
    context (e.g. in tests or standalone scripts) it becomes a top-level
    generation.

    Token counts are normalised to the standard Langfuse v5 ``usage_details``
    dict (``input_tokens`` / ``output_tokens`` / ``total_tokens``).
    """
    client = _get_client()
    if client is None:
        return

    try:
        # Normalise usage dict – accept both openai-style and direct field names.
        usage_details: dict[str, int] | None = None
        if usage and isinstance(usage, dict):
            # OpenAI-compatible keys
            normalized: dict[str, int] = {}
            for dest, candidates in (
                ("input_tokens", ("input_tokens", "prompt_tokens")),
                ("output_tokens", ("output_tokens", "completion_tokens")),
                ("total_tokens", ("total_tokens",)),
            ):
                for src in candidates:
                    val = usage.get(src)
                    if isinstance(val, int):
                        normalized[dest] = val
                        break
            if normalized:
                usage_details = normalized

        with client.start_as_current_observation(
            as_type="generation",
            name=name,
            model=model,
            input=input_data,
            metadata=metadata or {},
        ) as gen:
            gen.update(
                output=output_data,
                usage_details=usage_details,
                level="ERROR" if error else "DEFAULT",
                status_message=error,
            )
    except Exception as exc:
        logger.debug("Failed to record generation in Langfuse (%s): %s", name, exc)


# ---------------------------------------------------------------------------
# Lifecycle helpers
# ---------------------------------------------------------------------------

def flush_traces() -> None:
    """Flush any queued observations to Langfuse (call before process exit)."""
    client = _get_client()
    if client is None:
        return
    try:
        client.flush()
    except Exception:
        pass
