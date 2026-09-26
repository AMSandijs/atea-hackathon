"""The ordered local sanitization pipeline."""

from __future__ import annotations

import re

from .classify import classify
from .config import Policy
from .detect import entropy, model, rules
from .models import Finding, Sanitized
from .vault import Vault


def _prose_spans(text: str, findings: list[Finding]) -> list[tuple[int, str]]:
    spans: list[tuple[int, str]] = []
    candidates: list[tuple[int, int]] = []
    paragraph_start = 0
    for paragraph in text.splitlines(keepends=True):
        paragraph_end = paragraph_start + len(paragraph)
        if (
            paragraph.strip()
            and any(character.isalpha() for character in paragraph)
            and not paragraph.lstrip().startswith(("{", "[", '"'))
        ):
            candidates.append((paragraph_start, paragraph_end))
        paragraph_start = paragraph_end
    for match in re.finditer(r'"[A-Za-z][A-Za-z0-9_]*"\s*:\s*"(?P<value>(?:[^"\\]|\\.)*)"', text):
        if "\\" not in match.group("value"):
            candidates.append(match.span("value"))
    for start, end in candidates:
        cursor = start
        for finding in sorted(findings, key=lambda item: item.start):
            if finding.end <= start or finding.start >= end:
                continue
            covered_start = max(start, finding.start)
            if cursor < covered_start:
                spans.append((cursor, text[cursor:covered_start]))
            cursor = max(cursor, min(end, finding.end))
        if cursor < end:
            spans.append((cursor, text[cursor:end]))
    return spans


def _deduplicate(findings: list[Finding]) -> list[Finding]:
    """Keep the longest overlapping match, then the highest-confidence match."""

    selected: list[Finding] = []
    for finding in sorted(findings, key=lambda item: (-(item.end - item.start), -item.score, item.start)):
        if any(finding.start < other.end and other.start < finding.end for other in selected):
            continue
        selected.append(finding)
    return sorted(selected, key=lambda item: item.start)


_MIN_KNOWN_CHARS = 5


def _known_mentions(text: str, findings: list[Finding], vault: Vault) -> list[Finding]:
    """Find further mentions of originals the vault already maps (e.g. a bare resource name)."""

    originals = sorted(
        (value for value in vault.known_originals() if len(value) >= _MIN_KNOWN_CHARS),
        key=len,
        reverse=True,
    )
    if not originals:
        return []
    alternation = "|".join(re.escape(value).replace(r"\ ", r"\s+") for value in originals)
    pattern = re.compile(rf"(?<![\w-])(?:{alternation})(?![\w-])", re.IGNORECASE)
    taken = [(finding.start, finding.end) for finding in findings]
    mentions: list[Finding] = []
    for match in pattern.finditer(text):
        start, end = match.span()
        if any(start < other_end and other_start < end for other_start, other_end in taken):
            continue
        entity_type = vault.known_entity_type(match.group(0)) or "AZURE_RESOURCE_NAME"
        mentions.append(Finding(entity_type, match.group(0), start, end, "vault", 1.0, "swap"))
        taken.append((start, end))
    return mentions


def sanitize(text: str, policy: Policy, vault: Vault, strict_model: bool = False) -> Sanitized:
    """Detect, classify, and replace sensitive spans without sending anything."""

    deterministic = rules.detect(text, policy)
    deterministic.extend(entropy.detect(text, policy))
    deterministic = classify(deterministic, policy)
    blocked = [finding for finding in deterministic if finding.tier == "block"]
    if blocked:
        low_confidence = [
            finding for finding in deterministic if finding.score < policy.thresholds.review_below
        ]
        return Sanitized(text, deterministic, {}, blocked, low_confidence)
    prose_spans = _prose_spans(text, deterministic)
    model_findings = model.detect_prose(prose_spans, policy, strict=strict_model)
    findings = _deduplicate(deterministic + classify(model_findings, policy))
    blocked = [finding for finding in findings if finding.tier == "block"]
    low_confidence = [
        finding for finding in findings if finding.score < policy.thresholds.review_below
    ]
    if blocked:
        return Sanitized(text, findings, {}, blocked, low_confidence)

    replacements: list[tuple[Finding, str]] = []
    mapping: dict[str, str] = {}
    for finding in findings:
        if finding.tier != "swap":
            continue
        stand_in = vault.stand_in(finding)
        replacements.append((finding, stand_in))
        mapping.update(vault.related_pairs(finding))
    known = _known_mentions(text, findings, vault)
    for finding in known:
        replacements.append((finding, vault.stand_in(finding)))
        mapping.update(vault.related_pairs(finding))
    findings = sorted(findings + known, key=lambda item: item.start)
    sanitized_text = text
    for finding, stand_in in sorted(replacements, key=lambda item: item[0].start, reverse=True):
        sanitized_text = sanitized_text[: finding.start] + stand_in + sanitized_text[finding.end :]
    return Sanitized(sanitized_text, findings, mapping, [], low_confidence)
