from pathlib import Path

from airlock.config import load_policy
from airlock.models import Finding
from airlock.sanitize import sanitize
from airlock.vault import Vault


def test_block_finding_aborts_without_mapping(tmp_path: Path) -> None:
    policy = load_policy()
    source = "STORAGE_KEY=Xo9vK2mA7pQ1sR4tU6wY8zB0cD3eF5gH"
    result = sanitize(source, policy, Vault(b"key", tmp_path / "vault.json"))
    assert result.text == source
    assert result.mapping == {}
    assert result.blocked
    assert result.blocked[0].tier == "block"


def test_swap_replaces_right_to_left_and_preserves_pass_through(tmp_path: Path) -> None:
    policy = load_policy()
    source = "owner: Lars Olesen at nordbro-rmq-prd.westeurope.cloudapp.azure.com, code 500"
    result = sanitize(source, policy, Vault(b"key", tmp_path / "vault.json"))
    assert result.blocked == []
    assert "Lars Olesen" not in result.text
    assert "nordbro-rmq-prd.westeurope.cloudapp.azure.com" not in result.text
    assert "code 500" in result.text
    assert len(result.mapping) >= 2


def test_longest_overlap_wins() -> None:
    import airlock.sanitize as sanitize_module

    findings = [
        Finding("SHORT", "customer", 0, 8, "rules", 1.0),
        Finding("LONG", "customer-name", 0, 13, "rules", 0.7),
        Finding("OVERLAP", "name", 9, 13, "rules", 1.0),
    ]
    assert [finding.entity_type for finding in sanitize_module._deduplicate(findings)] == ["LONG"]


def test_azure_vm_snapshot_keeps_type_and_cpu_evidence(tmp_path: Path) -> None:
    source = (
        '{"resourceId":"/subscriptions/8f4c2b91-3d07-4a1e-b8c2-77e3a9d61f04/'
        'resourceGroups/nordbro-prd-rg/providers/Microsoft.Compute/virtualMachines/qconv-vm-prd",'
        '"vmName":"qconv-vm-prd","metric":"Percentage CPU","average":96.4,"process":"sqlservr.exe"}'
    )
    result = sanitize(source, load_policy(), Vault(b"azure", tmp_path / "vault.json"))
    assert not result.blocked
    assert "Microsoft.Compute/virtualMachines" in result.text
    assert "Percentage CPU" in result.text
    assert "96.4" in result.text
    assert "sqlservr.exe" in result.text
    assert "8f4c2b91" not in result.text
    assert "nordbro" not in result.text
    assert "qconv" not in result.text


def test_block_wins_even_when_overlapped_by_longer_swap(tmp_path: Path, monkeypatch) -> None:
    from airlock.detect import entropy, rules

    source = "example.invalid/key-fragment"
    monkeypatch.setattr(
        rules,
        "detect",
        lambda text, policy: [Finding("HOSTNAME", source, 0, len(source), "rules", 0.95)],
    )
    monkeypatch.setattr(
        entropy,
        "detect",
        lambda text, policy: [Finding("SECRET_UNKNOWN", "key-fragment", 16, 28, "entropy", 0.9)],
    )
    result = sanitize(source, load_policy(), Vault(b"key", tmp_path / "vault.json"))
    assert result.blocked
    assert result.text == source
    assert result.mapping == {}
