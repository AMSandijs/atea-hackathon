import warnings
from pathlib import Path

from airlock.classify import classify
from airlock.config import load_policy
from airlock.models import Finding


def test_every_policy_entity_type_gets_its_declared_tier() -> None:
    policy = load_policy(Path(__file__).parents[1] / "policy.yaml")
    findings = [
        Finding(entity_type, "value", 0, 5, "rules", 1.0)
        for entity_type in policy.tiers.block + policy.tiers.swap + policy.tiers.pass_
    ]
    classified = classify(findings, policy)
    assert {finding.tier for finding in classified[: len(policy.tiers.block)]} == {"block"}
    assert all(
        finding.tier == "swap"
        for finding in classified[len(policy.tiers.block) : len(policy.tiers.block) + len(policy.tiers.swap)]
    )
    assert all(finding.tier == "pass" for finding in classified[-len(policy.tiers.pass_) :])


def test_unknown_entity_defaults_to_swap_and_warns() -> None:
    finding = Finding("NEW_DETECTOR_TYPE", "value", 0, 5, "rules", 0.6)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        classified = classify([finding], load_policy())
    assert classified[0].tier == "swap"
    assert "defaulting to swap" in str(caught[0].message)
