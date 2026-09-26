"""High-entropy fallback for secret formats not covered by deterministic rules."""

from __future__ import annotations

import math
import re

from ..config import Policy
from ..models import Finding

_TOKEN = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9][A-Za-z0-9+_-]{2,}(?![A-Za-z0-9])")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)
_SHA = re.compile(r"^[0-9a-f]{40,64}$", re.IGNORECASE)
_ALLOWLIST = {"authorization", "application", "configuration", "documentation"}
_SEPARATOR = re.compile(r"[-_]")
_NAME_SEGMENT = re.compile(r"[a-z]{1,16}|[0-9]{1,4}|[a-z0-9]{1,4}")


def shannon_entropy(value: str) -> float:
    """Return Shannon entropy in bits per character."""

    if not value:
        return 0.0
    counts = {character: value.count(character) for character in set(value)}
    return -sum((count / len(value)) * math.log2(count / len(value)) for count in counts.values())


def _is_naming_convention(value: str) -> bool:
    """Lowercase, separator-delimited words and short counters, e.g. kv-app-weu-001."""

    if value != value.lower() or not _SEPARATOR.search(value):
        return False
    segments = _SEPARATOR.split(value)
    return all(segment and _NAME_SEGMENT.fullmatch(segment) for segment in segments)


def _is_allowed(value: str) -> bool:
    lowered = value.lower()
    return (
        lowered in _ALLOWLIST
        or bool(_UUID.fullmatch(lowered))
        or bool(_SHA.fullmatch(lowered))
        or _is_naming_convention(value)
    )


def detect(text: str, policy: Policy) -> list[Finding]:
    """Flag unknown long tokens whose entropy exceeds the configured threshold."""

    threshold = policy.thresholds.entropy_min_bits
    minimum_length = policy.thresholds.entropy_min_length
    findings: list[Finding] = []
    for match in _TOKEN.finditer(text):
        value = match.group(0)
        if len(value) < minimum_length or _is_allowed(value):
            continue
        entropy = shannon_entropy(value)
        if entropy >= threshold:
            score = min(0.99, max(0.55, entropy / 8))
            findings.append(Finding("SECRET_UNKNOWN", value, match.start(), match.end(), "entropy", score))
    return findings
