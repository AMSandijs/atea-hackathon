"""Restore stand-ins in model answers without touching invented neighbours."""

from __future__ import annotations

import re


def _split_candidates(stand_in: str, original: str) -> list[tuple[str, str]]:
    candidates = [(stand_in, original)]
    labels = stand_in.split(".")
    original_labels = original.split(".")
    if len(labels) >= 3 and len(labels) == len(original_labels):
        if stand_in.lower().endswith(".cloudapp.azure.com"):
            suffix_length = 4 if len(labels) > 4 else 3
        elif stand_in.lower().endswith(".azurewebsites.net"):
            suffix_length = 2
        else:
            return candidates
        if len(labels) > suffix_length:
            candidates.append(
                (
                    ".".join(labels[: len(labels) - suffix_length]),
                    ".".join(original_labels[: len(original_labels) - suffix_length]),
                )
            )
    return candidates


def _flexible_pattern(value: str) -> str:
    return "".join(
        re.escape(character) + (r"\s*" if index < len(value) - 1 else "")
        for index, character in enumerate(value)
    )


def _unmapped(answer: str, mapping: dict[str, str]) -> list[str]:
    residual: set[str] = set()
    for stand_in in mapping:
        prefix = stand_in
        suffix_match = re.search(r"(?i)([-_](?:dev|test|qa|uat|prd|prod))(?:\.|$)", stand_in)
        if suffix_match:
            prefix = stand_in[: suffix_match.start() + 1]
        pattern = re.compile(_flexible_pattern(stand_in), re.IGNORECASE)
        residual.update(match.group(0) for match in pattern.finditer(answer))
        if prefix != stand_in:
            neighbour = re.compile(re.escape(prefix) + r"[A-Za-z0-9-]*", re.IGNORECASE)
            residual.update(match.group(0) for match in neighbour.finditer(answer))
    return sorted(residual, key=lambda value: (value.lower(), value))


def rehydrate(answer: str, mapping: dict[str, str]) -> tuple[str, list[str]]:
    """Replace full and identifying-segment stand-ins, case-insensitively."""

    replacements: list[tuple[str, str]] = []
    for stand_in, original in mapping.items():
        replacements.extend(_split_candidates(stand_in, original))
    replacements.sort(key=lambda pair: len(pair[0]), reverse=True)
    rebuilt = answer
    for stand_in, original in replacements:
        rebuilt = re.sub(
            _flexible_pattern(stand_in),
            lambda _, replacement=original: replacement,
            rebuilt,
            flags=re.IGNORECASE,
        )
    return rebuilt, _unmapped(rebuilt, mapping)
