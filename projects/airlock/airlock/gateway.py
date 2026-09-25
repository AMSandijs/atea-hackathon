"""The single Airlock boundary where a sanitized payload may leave the machine."""

from __future__ import annotations

import json
import os
import time

import httpx

from .config import Policy
from .models import Sanitized


def _response_text(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text
    if isinstance(payload, dict):
        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message", {})
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                return message["content"]
        for key in ("output_text", "output", "text", "response"):
            if isinstance(payload.get(key), str):
                return payload[key]
    return json.dumps(payload)


def send(sanitized: Sanitized, policy: Policy) -> tuple[str, int]:
    """Send only sanitized text through the configured gateway.

    Without an endpoint the gateway runs an explicit local echo, which keeps the
    command usable in tests and offline demos while retaining one send boundary.
    """

    if sanitized.blocked:
        raise ValueError("blocked findings must be rotated before sending")
    endpoint = os.environ.get(policy.gateway.endpoint_env)
    if not endpoint:
        return sanitized.text, 0

    api_key = os.environ.get(policy.gateway.api_key_env)
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["api-key" if policy.gateway.provider == "azure_openai" else "Authorization"] = (
            api_key if policy.gateway.provider == "azure_openai" else f"Bearer {api_key}"
        )
    payload = {
        "model": policy.gateway.model,
        "messages": [{"role": "user", "content": sanitized.text}],
    }
    started = time.perf_counter()
    response = httpx.post(endpoint, headers=headers, json=payload, timeout=60.0)
    response.raise_for_status()
    return _response_text(response), int((time.perf_counter() - started) * 1000)
