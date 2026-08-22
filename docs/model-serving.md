# Local Model Serving (Qwen Coder / Qwen NLP)

Both models run **locally**, as their own vLLM OpenAI-compatible
server processes on the backend machine, using pre-downloaded weights.
No Ollama, no third-party model API — see `QwenProvider`
(`backend/src/model_layer/providers/qwen/provider.py`) and
`local_providers.py` in that same package for the client side; this
doc covers the server side.

## Architecture

```text
Backend (Gunicorn, N worker processes)
        |  HTTP, OpenAI-compatible /v1/chat/completions (+ SSE streaming)
        v
vLLM server process (1 per model, NOT per Gunicorn worker)
        |  loads weights once
        v
Pre-downloaded local weights (QWEN_*_MODEL_PATH)
```

One vLLM process per model, shared by every backend worker over the
network — not one per Gunicorn worker. A 7B model is ~14GB of weights
in bf16; loading it inside each of Gunicorn's `WEB_CONCURRENCY`
worker processes would multiply that by worker count, which is not
viable. This also means model serving scales independently of
backend request concurrency.

## Dependency isolation

Install vLLM in its **own** virtual environment, separate from
`backend/venv` — never add it to `backend/requirements.txt`. It pulls
in a multi-gigabyte, CUDA-specific PyTorch build the FastAPI process
itself never needs, and there is no reason to couple the API server's
dependency graph to it.

```bash
python3.11 -m venv /opt/ai-platform/model-runtime-venv
source /opt/ai-platform/model-runtime-venv/bin/activate
pip install vllm
```

Exact version/CUDA-build selection depends on your GPU/driver —
consult vLLM's own installation docs for the combination matching your
hardware; not specified here, since that constraint is
environment-specific and not something this repository can pin.

## Configuration

The server side reads the **same** `backend/.env` variables the
`QwenProvider` client already uses (see
`backend/src/model_layer/providers/qwen/config.py`) — deliberately one
source of configuration, not two:

| Variable | Used for |
|---|---|
| `QWEN_{CODER,NLP}_MODEL_PATH` | local path or HF repo id of the pre-downloaded weights |
| `QWEN_{CODER,NLP}_ENDPOINT_URL` | host:port to bind the server to (must match what the backend calls) |
| `QWEN_{CODER,NLP}_CONTEXT_LENGTH` | `--max-model-len` |
| `QWEN_{CODER,NLP}_DTYPE` | `--dtype` |
| `QWEN_{CODER,NLP}_GPU_MEMORY_FRACTION` | `--gpu-memory-utilization` |
| `QWEN_{CODER,NLP}_DEVICE` | only passed through if not `cuda` (vLLM's default) |
| `QWEN_{CODER,NLP}_API_KEY` | optional, `--api-key` |

`backend/scripts/run_local_model_server.sh` does this translation —
see that file for exact flag mapping. **Models are assumed already
downloaded** at `QWEN_*_MODEL_PATH`; this script does not download
anything.

## Starting manually (verification before systemd)

```bash
source /opt/ai-platform/model-runtime-venv/bin/activate
set -a; source /opt/ai-platform/app/backend/.env; set +a
MODEL_PREFIX=QWEN_CODER /opt/ai-platform/app/backend/scripts/run_local_model_server.sh
```

Verify: `curl http://<QWEN_CODER host:port>/v1/models` returns 200.

## systemd services

One unit per model, using the model-runtime venv (not the backend
venv), reading `backend/.env` for both the script's own variable
translation and anything else it needs:

`/etc/systemd/system/ai-platform-model-coder.service`:

```ini
[Unit]
Description=AI Platform - local Qwen Coder model server (vLLM)
After=network.target

[Service]
Type=simple
User=aiplatform
Group=aiplatform
WorkingDirectory=/opt/ai-platform/app/backend
EnvironmentFile=/opt/ai-platform/app/backend/.env
Environment=MODEL_PREFIX=QWEN_CODER
ExecStart=/opt/ai-platform/model-runtime-venv/bin/bash /opt/ai-platform/app/backend/scripts/run_local_model_server.sh
Restart=on-failure
RestartSec=10
TimeoutStartSec=300

[Install]
WantedBy=multi-user.target
```

`ai-platform-model-nlp.service` is identical except
`Environment=MODEL_PREFIX=QWEN_NLP`.

`ExecStart` uses the model-runtime venv's `bash` only to guarantee
`vllm` resolves from that venv's `PATH` — if you activate the venv
differently in your environment, adjust `ExecStart` accordingly; what
matters is that `vllm` on `PATH` when the script runs is the one from
the model-runtime venv, not the backend's.

```bash
sudo systemctl daemon-reload
sudo systemctl enable ai-platform-model-coder ai-platform-model-nlp
sudo systemctl start ai-platform-model-coder ai-platform-model-nlp
```

Start these **before** the backend (`ai-platform-backend.service`) —
see the manual-deployment `README.md`'s startup-order section, which
this slots into directly.

## GPU memory

Both models loaded simultaneously need either two GPUs, or one GPU
with `QWEN_*_GPU_MEMORY_FRACTION` budgeted across both (their sum must
stay under 1.0 with headroom for KV cache — e.g. `0.45` each, not
`0.5`/`0.5`). A 7B model in bf16 is ~14GB of weights alone before
vLLM's own KV-cache allocation on top.

## CPU fallback

vLLM's primary target is GPU inference; CPU-only operation exists but
is markedly slower and has narrower feature/quantization support. Set
`QWEN_*_DEVICE=cpu` only if no GPU is available and reduced throughput
is acceptable — validate this path yourself against the vLLM version
you install; not exercised by this repository's tests.

## Health / troubleshooting

See the manual-deployment `README.md`'s Troubleshooting → "Model
unavailable" section — unchanged by this doc, since `QwenProvider`'s
error handling (connection failures, timeouts, malformed responses)
already covers "server unreachable" the same way regardless of what
runs on the other end of the HTTP connection.
