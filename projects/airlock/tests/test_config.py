from pathlib import Path

from airlock.config import load_policy


def test_default_policy_loads() -> None:
    policy = load_policy(Path(__file__).parents[1] / "policy.yaml")
    assert policy.version == 1
    assert "SECRET_KEY" in policy.tiers.block
