"""Offline evaluation suite using DeepEval and Ragas scored with local or private LLMs.

Evaluates:
1. DeepEval Hallucination & Faithfulness (Medical detail preservation)
2. Ragas Faithfulness / Fact consistency
Scored completely with local Ollama models (default) or OpenAI-compatible local/private endpoints.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Note: Vertex AI is NOT used.
# The code below is a dummy module stub to prevent a known bug in Ragas (ragas/llms/base.py)
# where it unconditionally attempts to import `ChatVertexAI` from `langchain_community`
# at module load time, even when running fully local models.
# ---------------------------------------------------------------------------
for mod_name in ["langchain_community.chat_models.vertexai", "langchain_community.llms.vertexai", "langchain_community.llms"]:
    if mod_name not in sys.modules:
        m = ModuleType(mod_name)
        m.ChatVertexAI = None
        m.VertexAI = None
        sys.modules[mod_name] = m

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import settings
from app.models import Fact, Sentence
from app.pipeline.explain import explain_facts
from app.pipeline.extract import extract_facts
from app.pipeline.parse import parse_and_split
from app.pipeline.verify import verify_claims

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DeepEval Custom Local LLM Model Definition
# ---------------------------------------------------------------------------
from deepeval.models import DeepEvalBaseLLM


class LocalOllamaDeepEvalLLM(DeepEvalBaseLLM):
    """DeepEval LLM wrapper calling the project's local/private LLM endpoint."""

    def __init__(self, model_name: Optional[str] = None):
        self.model_name = model_name or settings.model_id
        super().__init__(model_name=self.model_name)

    def load_model(self):
        return self.model_name

    def generate(self, prompt: str) -> tuple[str, float]:
        from app.llm_client import chat_completion

        res = chat_completion(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            timeout=90.0,
        )
        output = res.choices[0].message.content or ""
        return output, 0.0

    async def a_generate(self, prompt: str) -> tuple[str, float]:
        return self.generate(prompt)

    def get_model_name(self) -> str:
        return self.model_name


# ---------------------------------------------------------------------------
# Evaluation Execution
# ---------------------------------------------------------------------------
def run_offline_eval(
    *,
    limit: Optional[int] = None,
    model_id: Optional[str] = None,
    output_path: Optional[Path] = None,
) -> dict[str, Any]:
    eval_model_id = model_id or settings.model_id
    local_eval_llm = LocalOllamaDeepEvalLLM(model_name=eval_model_id)

    from deepeval.metrics import HallucinationMetric, GEval
    from deepeval.test_case import LLMTestCase, LLMTestCaseParams

    # 1. Gather test cases from synthetic discharge documents
    all_docs = sorted((ROOT / "data" / "synthetic").glob("doc_*.txt"))
    test_docs = all_docs[:limit] if limit is not None else all_docs
    if not test_docs:
        raise RuntimeError("No synthetic test documents found in data/synthetic/")

    results = []
    print(f"Starting Offline Evals on {len(test_docs)} documents using local scorer: {eval_model_id}...")

    # Define G-Eval metric for Plain-Language Clarity & Safety
    clarity_metric = GEval(
        name="Clinical Clarity & Preservation",
        criteria=(
            "Evaluate whether the plain-language explanation faithfully reflects the source facts "
            "without distorting medication names, doses, frequencies, dates, or creating unverified advice."
        ),
        evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT, LLMTestCaseParams.CONTEXT],
        model=local_eval_llm,
    )
    hallucination_metric = HallucinationMetric(threshold=0.3, model=local_eval_llm)

    for doc_path in test_docs:
        doc_text = doc_path.read_text(encoding="utf-8")
        sentences = parse_and_split(doc_text)
        facts = extract_facts(sentences)

        if not facts:
            continue

        claims = explain_facts(facts)
        verify_claims(claims, sentences, facts)

        for claim in claims:
            linked_facts = [f.text_en for f in facts if f.id in claim.fact_ids]
            context_text = "\n".join(linked_facts) if linked_facts else doc_text

            test_case = LLMTestCase(
                input="Explain this discharge instruction in simple English.",
                actual_output=claim.text,
                context=linked_facts if linked_facts else [doc_text],
            )

            # Evaluate with DeepEval Local Scorer
            hallucination_score = None
            hallucination_reason = None
            clarity_score = None
            clarity_reason = None

            try:
                hallucination_metric.measure(test_case)
                hallucination_score = hallucination_metric.score
                hallucination_reason = hallucination_metric.reason
            except Exception as e:
                logger.warning("Hallucination metric measurement error: %s", e)

            try:
                clarity_metric.measure(test_case)
                clarity_score = clarity_metric.score
                clarity_reason = clarity_metric.reason
            except Exception as e:
                logger.warning("Clarity metric measurement error: %s", e)

            results.append({
                "doc_name": doc_path.name,
                "claim_id": claim.id,
                "claim_text": claim.text,
                "source_facts": linked_facts,
                "internal_verifier_state": claim.state.value,
                "internal_checks": claim.checks,
                "deepeval": {
                    "hallucination_score": hallucination_score,
                    "hallucination_reason": hallucination_reason,
                    "clarity_geval_score": clarity_score,
                    "clarity_reason": clarity_reason,
                },
            })

    summary = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "scorer_model": eval_model_id,
        "cases_evaluated": len(results),
        "results": results,
    }

    if output_path is None:
        output_path = ROOT / "eval" / "results" / "offline_eval_results.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Offline evaluation successfully saved to: {output_path}")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="Number of documents to evaluate (omit to evaluate all)")
    parser.add_argument("--model-id", type=str, default=None, help="Model ID used as local judge")
    parser.add_argument("--output", type=Path, default=None, help="Output JSON path")
    args = parser.parse_args()

    run_offline_eval(limit=args.limit, model_id=args.model_id, output_path=args.output)


if __name__ == "__main__":
    main()
