"""
Externalized configuration for the ILA agent adapter — same pattern
as `model_layer/providers/qwen/config.py`: everything sourced from
environment variables, nothing hardcoded.

`constructor_kwargs` exists because ILA's actual constructor
signature (`ILA(**kwargs)`) is owned by the ILA module itself, not by
this platform — this adapter deliberately does not hardcode assumed
kwarg names it doesn't actually know. Whatever `ILA_CONSTRUCTOR_KWARGS`
(a JSON object) contains is forwarded verbatim. `ILA_DEFAULT_MODEL_KEY`
is forwarded too, under a name ILA is expected to look for if it
wants model access via the platform's existing `ModelRouter` — see
`adapters/ila_adapter.py`; if ILA's real constructor uses a different
parameter name for this, only that one mapping needs to change.
"""
from __future__ import annotations

import json
import os

from pydantic import BaseModel


class ILAAgentConfig(BaseModel):
    agent_key: str = "ila-agent"
    display_name: str = "ILA Agent"

    # Dotted import path to the module containing the ILA class, and
    # the class name itself — e.g. module_path="ila_engineering_agent",
    # class_name="ILA" for `from ila_engineering_agent import ILA`.
    # Resolved dynamically (importlib) rather than imported directly
    # by this file, so this package has no hard dependency on the ILA
    # module actually being installed unless ILA_ENABLED=true.
    module_path: str
    class_name: str = "ILA"

    # Forwarded verbatim as ILA(**constructor_kwargs). See module
    # docstring for why this isn't a fixed set of named fields.
    constructor_kwargs: dict = {}

    # Which registered model_key (if any) this adapter hands to ILA
    # for its own model calls — see ila_adapter.py.
    default_model_key: str | None = None

    # ILA(**kwargs).main(query=...) is a plain blocking call — run in
    # a thread so it never blocks the event loop (see ila_adapter.py).
    # Long enough for a multi-step agent run; short enough to not hang
    # a request forever if ILA itself gets stuck.
    timeout_seconds: float = 300.0


def load_ila_config() -> ILAAgentConfig:
    module_path = os.environ.get("ILA_MODULE_PATH", "").strip()
    if not module_path:
        raise ValueError("ILA_MODULE_PATH must be set when ILA_ENABLED=true.")

    raw_kwargs = os.environ.get("ILA_CONSTRUCTOR_KWARGS", "").strip()
    constructor_kwargs = json.loads(raw_kwargs) if raw_kwargs else {}
    if not isinstance(constructor_kwargs, dict):
        raise ValueError("ILA_CONSTRUCTOR_KWARGS must be a JSON object.")

    return ILAAgentConfig(
        module_path=module_path,
        class_name=os.environ.get("ILA_CLASS_NAME", "ILA").strip() or "ILA",
        constructor_kwargs=constructor_kwargs,
        default_model_key=os.environ.get("ILA_DEFAULT_MODEL_KEY", "").strip() or None,
        timeout_seconds=float(os.environ.get("ILA_TIMEOUT_SECONDS", "300")),
    )
