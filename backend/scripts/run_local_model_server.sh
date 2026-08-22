#!/usr/bin/env bash
# Starts a local vLLM OpenAI-compatible server for one Qwen model,
# reading the exact same env vars `src/model_layer/providers/qwen/config.py`
# reads for the HTTP client side -- see that file's module docstring
# and docs/model-serving.md. There is deliberately no second config
# file for "the model server" vs. "the client that talks to it."
#
# This script does NOT run inside the backend's own venv/process -- it
# is meant to run in vLLM's own, separate Python environment (see
# docs/model-serving.md, "Dependency isolation"), as its own long-lived
# process managed by systemd (ai-platform-model-coder.service /
# ai-platform-model-nlp.service).
#
# Usage:
#   MODEL_PREFIX=QWEN_CODER ./run_local_model_server.sh
#   MODEL_PREFIX=QWEN_NLP   ./run_local_model_server.sh
#
# Required env (via the prefix above, e.g. QWEN_CODER_MODEL_PATH):
#   {PREFIX}_MODEL_PATH        local path or HF repo id of the
#                              pre-downloaded model weights (required
#                              -- this script does not download
#                              anything; see docs/model-serving.md)
#   {PREFIX}_ENDPOINT_URL      used only to derive host:port to bind
#                              (e.g. http://localhost:8001/v1 -> :8001)
# Optional:
#   {PREFIX}_CONTEXT_LENGTH, {PREFIX}_DEVICE, {PREFIX}_DTYPE,
#   {PREFIX}_GPU_MEMORY_FRACTION, {PREFIX}_API_KEY
#
# Exact vLLM CLI flag names/behavior are version-dependent -- verify
# against `vllm serve --help` for the version actually installed in
# the model-serving venv before relying on this in production; the
# flags below are the stable, commonly-supported ones as of vLLM's
# OpenAI-compatible server (see https://docs.vllm.ai).

set -euo pipefail

: "${MODEL_PREFIX:?Set MODEL_PREFIX to QWEN_CODER or QWEN_NLP}"

model_path_var="${MODEL_PREFIX}_MODEL_PATH"
endpoint_var="${MODEL_PREFIX}_ENDPOINT_URL"
context_var="${MODEL_PREFIX}_CONTEXT_LENGTH"
device_var="${MODEL_PREFIX}_DEVICE"
dtype_var="${MODEL_PREFIX}_DTYPE"
gpu_frac_var="${MODEL_PREFIX}_GPU_MEMORY_FRACTION"
api_key_var="${MODEL_PREFIX}_API_KEY"

model_path="${!model_path_var:?Set ${model_path_var} to the pre-downloaded local model path or HF repo id}"
endpoint_url="${!endpoint_var:?Set ${endpoint_var} (e.g. http://localhost:8001/v1) to derive the bind port}"

# Extract host:port from the endpoint URL the backend is configured to
# call -- keeps a single source of truth (backend/.env) instead of a
# second, independently-set port for the server side.
without_scheme="${endpoint_url#*://}"
host_port="${without_scheme%%/*}"
bind_host="${host_port%%:*}"
bind_port="${host_port##*:}"
if [ "${bind_host}" = "0.0.0.0" ] || [ "${bind_host}" = "127.0.0.1" ] || [ "${bind_host}" = "localhost" ]; then
  : # fine as-is
else
  bind_host="0.0.0.0"  # backend reaches this over the network; do not bind to a client-facing hostname
fi

args=(serve "${model_path}" --host "${bind_host}" --port "${bind_port}")

context_length="${!context_var:-}"
[ -n "${context_length}" ] && args+=(--max-model-len "${context_length}")

dtype="${!dtype_var:-}"
[ -n "${dtype}" ] && args+=(--dtype "${dtype}")

gpu_fraction="${!gpu_frac_var:-}"
[ -n "${gpu_fraction}" ] && args+=(--gpu-memory-utilization "${gpu_fraction}")

device="${!device_var:-}"
if [ -n "${device}" ] && [ "${device}" != "cuda" ]; then
  # vLLM defaults to CUDA and selects the GPU via CUDA_VISIBLE_DEVICES
  # rather than a generic --device flag in most versions; "cuda" (the
  # repo's default) needs no flag. A non-default value here almost
  # always means CPU-only, which vLLM supports with markedly lower
  # throughput -- see docs/model-serving.md, "CPU fallback."
  args+=(--device "${device}")
fi

api_key="${!api_key_var:-}"
[ -n "${api_key}" ] && args+=(--api-key "${api_key}")

echo "Starting vLLM server for ${MODEL_PREFIX}: model=${model_path} bind=${bind_host}:${bind_port}" >&2
exec vllm "${args[@]}"
