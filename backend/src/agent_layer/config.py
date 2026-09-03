"""
Externalized configuration for the ILA agent adapter — same pattern
as `model_layer/providers/qwen/config.py`: everything sourced from
environment variables, nothing hardcoded.

ILA is a first-party module fixed at `backend/src/ila/` (imported as
`from src.ila import ILA` — see `adapters/ila_adapter.py`), not a
pluggable external package, so there's no module_path/class_name to
configure here anymore (removed — see git history if the previous,
dynamic-import version is needed for reference).

`chunk_path`/`vector_db_path`/`artifacts_dir`/`workspace_dir` are
ILA's documented constructor dependencies. Their exact constructor
KEYWORD names are not part of the interface given to this platform —
only the resulting instance attributes (`self.chunck_path` etc.) are.
Rather than guess a spelling (the shown attribute name has what looks
like a typo — "chunck_path" — that may or may not be reproduced in
the constructor's own kwarg name), each is exposed as its own,
correctly-spelled env var for operator clarity, merged into
`constructor_kwargs` under the correctly-spelled key by default; the
escape hatch (`ILA_CONSTRUCTOR_KWARGS`, applied AFTER and so able to
override any key) exists specifically so a spelling mismatch against
the real constructor can be corrected without a code change. Whoever
wires this up for real should confirm the actual kwarg names against
`backend/src/ila/`'s `__init__` and adjust the merge below if needed.
"""
from __future__ import annotations

import json
import os

from pydantic import BaseModel


class ILAAgentConfig(BaseModel):
    agent_key: str = "ila-agent"
    display_name: str = "ILA Agent"

    # Forwarded as ILA(**constructor_kwargs). Built from the four
    # named env vars below, then overlaid with ILA_CONSTRUCTOR_KWARGS
    # (JSON) if set — see module docstring for why both exist.
    constructor_kwargs: dict = {}

    # Which registered model_key (if any) this adapter hands to ILA
    # for its own model calls — see ila_adapter.py. Unrelated to the
    # constructor kwargs above; forwarded separately under its own
    # assumed key ("model_router") in ila_adapter.py.
    default_model_key: str | None = None

    # ILA.generate(...) is a plain blocking call — run in a thread so
    # it never blocks the event loop (see ila_adapter.py). Long enough
    # for a multi-step agent run; short enough to not hang a request
    # forever if ILA itself gets stuck.
    timeout_seconds: float = 300.0

    # Applied when a SendMessageRequest.ila omits them (mode/
    # overwrite_step are the two fields with a defensible generic
    # default; function_name/step/output_file are not — see
    # schemas/message.py's SendMessageRequest.ila docstring).
    default_mode: str = "generate"
    default_overwrite_step: bool = False


def load_ila_config() -> ILAAgentConfig:
    constructor_kwargs: dict = {}
    for env_var, key in (
        ("ILA_CHUNK_PATH", "chunk_path"),
        ("ILA_VECTOR_DB_PATH", "vector_db_path"),
        ("ILA_ARTIFACTS_DIR", "artifacts_dir"),
        ("ILA_WORKSPACE_DIR", "workspace_dir"),
    ):
        value = os.environ.get(env_var, "").strip()
        if value:
            constructor_kwargs[key] = value

    raw_overrides = os.environ.get("ILA_CONSTRUCTOR_KWARGS", "").strip()
    if raw_overrides:
        overrides = json.loads(raw_overrides)
        if not isinstance(overrides, dict):
            raise ValueError("ILA_CONSTRUCTOR_KWARGS must be a JSON object.")
        constructor_kwargs.update(overrides)

    return ILAAgentConfig(
        constructor_kwargs=constructor_kwargs,
        default_model_key=os.environ.get("ILA_DEFAULT_MODEL_KEY", "").strip() or None,
        timeout_seconds=float(os.environ.get("ILA_TIMEOUT_SECONDS", "300")),
        default_mode=os.environ.get("ILA_DEFAULT_MODE", "generate").strip() or "generate",
        default_overwrite_step=os.environ.get("ILA_DEFAULT_OVERWRITE_STEP", "false").strip().lower()
        in ("1", "true", "yes", "on"),
    )
