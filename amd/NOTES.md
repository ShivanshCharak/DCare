# AMD deployment notes

## Selected model baseline (not yet runtime-verified)

- Model ID: `Qwen/Qwen2.5-7B-Instruct`
- Reason: its model card documents vLLM serving and JSON-structured output support; AMD ROCm documentation lists the related Qwen2 7B family on MI300X. The exact Qwen2.5 model, container, and Developer Cloud instance still need a live smoke test.
- License reported on model card: Apache-2.0. Review the model card and intended-use terms before distribution.

## Runtime notes (fill in only after testing)

- Developer Cloud instance / GPU:
- ROCm version:
- Container image and tag:
- vLLM version:
- Model ID and revision:
- Exact serve command:
- Smoke test result:
- Hourly cost / credits remaining:
- Measured benchmark results:
- Known failures and fallback demo plan:

Keep endpoint authentication enabled and restrict network access. Do not commit credentials.
