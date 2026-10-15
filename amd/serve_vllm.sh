#!/usr/bin/env bash
set -euo pipefail

# TEMPLATE ONLY. Confirm current ROCm image tag, GPU flags, model ID and vLLM CLI.
: "${HF_TOKEN:?Set HF_TOKEN in your shell}"
: "${VLLM_API_KEY:?Set VLLM_API_KEY in your shell}"
: "${MODEL_ID:?Set MODEL_ID to a model supported by the instance}"

echo "Review current AMD ROCm/vLLM documentation before enabling this template."
# Example shape; replace <verified-rocm-vllm-image> with the current documented image.
# docker run --rm --ipc=host --shm-size 16g \
#   --device=/dev/kfd --device=/dev/dri --group-add video \
#   -p 8000:8000 -v "$HOME/hf_cache:/root/.cache/huggingface" \
#   -e HF_TOKEN="$HF_TOKEN" <verified-rocm-vllm-image> \
#   vllm serve "$MODEL_ID" --host 0.0.0.0 --port 8000 \
#   --max-model-len 8192 --api-key "$VLLM_API_KEY"
