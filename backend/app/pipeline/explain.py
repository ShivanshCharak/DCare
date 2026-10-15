import logging
import re

from ..config import settings
from ..llm_client import chat_completion
from ..models import Claim, Fact, State

logger = logging.getLogger(__name__)


def generate_explanation(fact: Fact) -> str:
    """Generate a plain-English explanation of one extracted fact."""

    response = chat_completion(
        model=settings.model_id,
        messages=[
            {
                "role": "system",
                "content": (
                    "You explain discharge instructions in simple English. "
                    "Use short, familiar words and explain medical terms when this can be done "
                    "without changing their meaning. For diagnosis statements, briefly explain "
                    "what the diagnosis means in everyday words. Avoid copying the source "
                    "sentence word for word unless it is already the clearest safe wording. "
                    "Prefer natural wording over literal paraphrases. Describe an observation "
                    "period as a time the patient was monitored, not a time they were being watched. "
                    "Use only information supported by the supplied source. "
                    "Never invent medical advice or new instructions. "
                    "Do not attribute an instruction to a clinician unless the source says who gave it. "
                    "Never change medication names, doses, frequencies, "
                    "durations, dates, or follow-up instructions. "
                    "If the source is unclear, preserve its meaning rather "
                    "than guessing. Return only the explanation."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Rewrite the following extracted discharge fact in "
                    "simple English without changing its meaning.\n\n"
                    f"Fact type: {fact.kind}\n"
                    f"Source fact: {fact.text_en}"
                ),
            },
        ],
        temperature=0,
        timeout=60.0,
    )

    explanation = response.choices[0].message.content

    if not explanation or not explanation.strip():
        raise ValueError("The model returned an empty explanation.")

    explanation = explanation.strip()
    # Avoid a literal, surveillance-like paraphrase of clinical monitoring.
    explanation = re.sub(r"\bwere being watched\b", "were monitored", explanation, flags=re.IGNORECASE)
    explanation = re.sub(r"\bwas being watched\b", "was monitored", explanation, flags=re.IGNORECASE)
    return explanation


def explain_facts(facts: list[Fact]) -> list[Claim]:
    """Generate explanations using the configured local Ollama model."""

    claims: list[Claim] = []

    for fact in facts:
        try:
            explanation = generate_explanation(fact)

            reason_codes = []

        except Exception:
            # Do not silently treat a failed model call as successful.
            logger.exception("Explanation generation failed fact_id=%s", fact.id)

            explanation = fact.text_en
            reason_codes = ["llm_generation_failed"]

        claims.append(
            Claim(
                id=f"C{len(claims) + 1}",
                text=explanation,
                language="en",
                fact_ids=[fact.id],
                source_ids=fact.source_ids,
                state=State.PENDING_VERIFACATION,
                reason_codes=reason_codes,
            )
        )

    return claims
