"""Policy classification for detector findings."""

from __future__ import annotations

import warnings
from dataclasses import replace

from .config import Policy
from .models import Finding


def _tier_map(policy: Policy) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for tier, entity_types in (
        ("block", policy.tiers.block),
        ("swap", policy.tiers.swap),
        ("pass", policy.tiers.pass_),
    ):
        for entity_type in entity_types:
            mapping[entity_type] = tier
    return mapping


def classify(findings: list[Finding], policy: Policy) -> list[Finding]:
    """Apply policy tiers, defaulting unknown entity types to ``swap``.

    Unknown types are deliberately visible to the caller through a warning. This
    prevents a newly added detector from silently becoming pass-through data.
    """

    mapping = _tier_map(policy)
    warned: set[str] = set()
    classified: list[Finding] = []
    for finding in findings:
        tier = mapping.get(finding.entity_type)
        if tier is None:
            tier = "swap"
            if finding.entity_type not in warned:
                warnings.warn(
                    f"entity type {finding.entity_type!r} is not listed in policy; defaulting to swap",
                    UserWarning,
                    stacklevel=2,
                )
                warned.add(finding.entity_type)
        classified.append(replace(finding, tier=tier))
    return classified
