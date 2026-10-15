"""Optional conservative local-model check for claim support by source facts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from ..config import settings
from ..llm_client import chat_completion


class EntailmentAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: Literal["supported", "unsupported", "uncertain"]
    unsupported_details: list[str]


def assess_entailment(claim_text: str, source_facts: list[str]) -> EntailmentAssessment:
    """Compare one claim with its linked facts; never assess clinical correctness."""
    schema = EntailmentAssessment.model_json_schema()
    response = chat_completion(
        model=settings.model_id,
        messages=[
            {
                "role": "system",
                "content": (
                    "Check whether every concrete detail in a plain-language claim is "
                    "supported by the supplied discharge source facts. Assess source "
                    "support only, not medical correctness. Mark unsupported only when "
                    "a concrete claim detail clearly conflicts with or is absent from the "
                    "sources. Use uncertain when the wording or relationship is ambiguous. "
                    "Do not infer missing clinical information. Return concise unsupported "
                    "details, or an empty list when there are none."
                ),
            },
            {
                "role": "user",
                "content": (
                    "SOURCE FACTS:\n"
                    + "\n".join(f"- {fact}" for fact in source_facts)
                    + f"\n\nCLAIM:\n{claim_text}"
                ),
            },
        ],
        temperature=0,
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "claim_entailment_assessment",
                "strict": True,
                "schema": schema,
            },
        },
        timeout=45.0,
    )
    content = response.choices[0].message.content
    if not content:
        raise ValueError("Entailment judge returned empty content")
    return EntailmentAssessment.model_validate_json(content)


def check_claim_entailment(
    claim_text: str,
    source_facts: list[str],
    *,
    enabled: bool,
) -> tuple[str, list[str]]:
    """Return a verifier status and conservative reason codes."""
    if not enabled:
        return "not_configured", []
    if not source_facts:
        return "not_run", []
    try:
        assessment = assess_entailment(claim_text, source_facts)
    except Exception:
        # Do not leak prompts, model output, or endpoint details into the UI/log.
        return "not_run", ["entailment_judge_failed"]

    if assessment.verdict == "supported":
        return "passed", []
    if assessment.verdict == "unsupported":
        return "failed", ["unsupported_claim_detail"]
    return "review_suggested", ["uncertain_claim_entailment"]
