"""Optional local-model sweep for person and organisation names in free prose."""

from __future__ import annotations

import ipaddress
import json
import os
import re
from urllib.parse import urlparse

import httpx

from ..config import Policy
from ..models import Finding

_SYSTEM = (
    "Find private PERSON and ORG_NAME mentions in the supplied text. "
    "Return only JSON of the form "
    '{"entities":[{"type":"PERSON","text":"exact substring","score":0.9}]}. '
    "Copy each entity exactly from the input text. Do not invent entities. "
    'When there are no private names, return exactly {"entities":[]}, never {}. '
    "Ignore Azure service names, product names, regions, and technical terms."
)


class LocalModelError(RuntimeError):
    """The configured local detector could not safely complete its sweep."""


def local_endpoint() -> str | None:
    """Return a validated local inference URL, or None when unconfigured."""

    raw = os.environ.get("AIRLOCK_LOCAL_MODEL_URL")
    if not raw:
        return None
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
        raise ValueError("local model URL must be HTTP(S) without embedded credentials")
    try:
        host = parsed.hostname
        loopback = host == "localhost" or (host is not None and ipaddress.ip_address(host).is_loopback)
    except ValueError:
        loopback = False
    if not loopback or not parsed.port:
        raise ValueError("local model URL must use a loopback host and explicit port")
    return raw


def _looks_like_prose(text: str) -> bool:
    words = re.findall(r"[A-Za-z]{3,}", text)
    stripped = text.strip()
    return (
        len(words) >= 4
        and not ("," in stripped and " " not in stripped)
        and not stripped.startswith(("{", "[", "param ", "resource ", "//"))
        and sum(character.isalpha() for character in text) / max(1, len(text)) >= 0.5
    )


def _chat(text: str, policy: Policy, endpoint: str, error: str = "") -> str:
    prompt = f"Text:\n{text}"
    if error:
        prompt += f"\nPrevious JSON was invalid: {error}. Return valid JSON only."
    messages = [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": prompt}]
    if policy.model.provider == "ollama":
        payload = {"model": policy.model.name, "messages": messages, "stream": False, "format": "json"}
    elif policy.model.provider in {"foundry_local", "lm_studio"}:
        payload = {
            "model": policy.model.name,
            "messages": messages,
            "temperature": 0,
        }
    else:
        raise ValueError("unsupported local model provider")
    response = httpx.post(endpoint, json=payload, timeout=120.0, trust_env=False)
    response.raise_for_status()
    body = response.json()
    if policy.model.provider == "ollama":
        return body["message"]["content"]
    return body["choices"][0]["message"]["content"]


def _parse(content: str, span: str, base: int, policy: Policy) -> list[Finding]:
    document = content.strip()
    if document.startswith("```"):
        fenced = re.fullmatch(r"```(?:json)?\s*\n(?P<body>.*?)\n```", document, re.IGNORECASE | re.DOTALL)
        if fenced is None:
            raise ValueError("invalid fenced JSON")
        document = fenced.group("body")
    raw = json.loads(document)
    if not isinstance(raw, dict) or not isinstance(raw.get("entities"), list):
        raise TypeError("expected an entities list")
    findings: list[Finding] = []
    for entity in raw["entities"]:
        if not isinstance(entity, dict):
            raise TypeError("entity must be an object")
        entity_type = entity.get("type")
        value, score = entity.get("text"), entity.get("score")
        if entity_type not in {"PERSON", "ORG_NAME"}:
            raise ValueError("unsupported entity type")
        if (
            not isinstance(value, str)
            or not value
            or type(score) not in {int, float}
            or not 0 <= score <= 1
        ):
            raise ValueError("invalid entity text or score")
        matches = list(re.finditer(r"(?<!\w)" + re.escape(value) + r"(?!\w)", span))
        if not matches:
            raise ValueError("model entity is not an exact substring")
        if score >= policy.thresholds.model_min_score:
            findings.extend(
                Finding(entity_type, value, base + match.start(), base + match.end(), "model", float(score))
                for match in matches
            )
    return findings


def detect_prose(spans: list[tuple[int, str]], config: Policy, strict: bool = False) -> list[Finding]:
    """Query a loopback-only model for rule-free prose, retrying malformed JSON once."""

    endpoint = local_endpoint()
    if endpoint is None:
        return []
    findings: list[Finding] = []
    for base, span in spans:
        if not _looks_like_prose(span):
            continue
        for offset in range(0, len(span), config.model.max_span_chars):
            chunk = span[offset : offset + config.model.max_span_chars]
            if not _looks_like_prose(chunk):
                continue
            error = ""
            for _ in range(2):
                try:
                    content = _chat(chunk, config, endpoint, error)
                    findings.extend(_parse(content, chunk, base + offset, config))
                    break
                except httpx.HTTPError as exc:
                    if strict:
                        raise LocalModelError("local model request failed; case was not released") from exc
                    break
                except (KeyError, TypeError, ValueError) as exc:
                    error = str(exc)
            else:
                if strict:
                    raise LocalModelError("local model returned invalid structured output; case was not released")
    return findings
