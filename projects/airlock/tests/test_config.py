from pathlib import Path

from airlock.config import load_policy


def test_default_policy_loads() -> None:
    policy = load_policy(Path(__file__).parents[1] / "policy.yaml")
    assert policy.version == 1
    assert "SECRET_KEY" in policy.tiers.block


def test_investigation_queue_defaults_and_bounds(tmp_path: Path) -> None:
    import pytest

    policy = load_policy(Path(__file__).parents[1] / "policy.yaml")
    assert policy.investigation.request_claim_seconds == 300
    assert policy.investigation.request_deadline_minutes == 30

    source = (Path(__file__).parents[1] / "policy.yaml").read_text(encoding="utf-8")
    for bad in ("request_claim_seconds: 5", "request_deadline_minutes: 600"):
        broken = tmp_path / "policy.yaml"
        broken.write_text(
            source.replace("request_claim_seconds: 300", bad)
            if "claim" in bad
            else source.replace("request_deadline_minutes: 30", bad),
            encoding="utf-8",
        )
        with pytest.raises(ValueError):
            load_policy(broken)
