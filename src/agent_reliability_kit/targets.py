"""Resolve a `--target` spec: a Python `module:callable`, or an HTTP(S) endpoint.

The HTTP form is what lets the CLI test an agent written in any language, or one
you'd rather not import into the test process: each case's `input` is POSTed
as the JSON body and the JSON response is the output scorers see.

    arkit run golden.jsonl -t https://staging.example.com/agent/invoke -s my_scorers:SCORERS

Request headers come from `AR_TARGET_HEADERS` (a JSON object), not a flag, so a
bearer token stays out of shell history and CI logs. `AR_TARGET_TIMEOUT` is in
seconds (default 120).
"""

from __future__ import annotations

import importlib
import json
import os
from collections.abc import Awaitable, Callable
from typing import Any

import httpx


def http_target(
    url: str, *, headers: dict[str, str] | None = None, timeout: float = 120.0
) -> Callable[[dict[str, Any]], Awaitable[Any]]:
    """An async target that POSTs the case input to `url`. Non-2xx raises, which
    the eval harness records as an errored case rather than a failed one."""

    async def call(payload: dict[str, Any]) -> Any:
        # ponytail: one client per call; share a client if connection setup shows up in latency.
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
        try:
            return resp.json()
        except ValueError:
            return resp.text

    call.__name__ = f"http_target({url})"
    return call


def load_target(spec: str) -> Callable[[dict[str, Any]], Any]:
    """`https://...` -> `http_target`; `pkg.module:attr` -> that attribute."""
    if spec.startswith(("http://", "https://")):
        try:
            headers = json.loads(os.environ.get("AR_TARGET_HEADERS") or "{}")
        except json.JSONDecodeError:
            headers = None
        if not isinstance(headers, dict):
            raise ValueError(
                'AR_TARGET_HEADERS must be a JSON object, e.g. {"Authorization": "Bearer ..."}'
            )
        timeout = float(os.environ.get("AR_TARGET_TIMEOUT") or 120)
        return http_target(spec, headers=headers, timeout=timeout)
    if ":" not in spec:
        raise ValueError(f"Expected module:attr or an http(s) URL, got {spec!r}")
    mod_path, attr = spec.split(":", 1)
    return getattr(importlib.import_module(mod_path), attr)
