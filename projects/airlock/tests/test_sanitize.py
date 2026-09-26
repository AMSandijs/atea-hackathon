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


_ARM = (
    "/subscriptions/8f4c2b91-3d07-4a1e-b8c2-77e3a9d61f04/resourceGroups/nordbro-prd-rg/providers/"
)


def test_metric_ids_sanitize_without_error_and_keep_the_metric_route(tmp_path: Path) -> None:
    source = (
        f'{{"id": "{_ARM}microsoft.insights/components/nordbro-web-ai/providers/'
        'Microsoft.Insights/metrics/requests/failed", "value": 188}\n'
        f'{{"id": "{_ARM}Microsoft.Compute/virtualMachines/nordbro-vm1/providers/'
        'Microsoft.Insights/metrics/Percentage CPU", "value": 97.5}'
    )
    result = sanitize(source, load_policy(), Vault(b"key", tmp_path / "vault.json"))
    assert result.blocked == []
    assert "nordbro" not in result.text
    assert "/providers/Microsoft.Insights/metrics/requests/failed" in result.text
    assert "/providers/Microsoft.Insights/metrics/Percentage CPU" in result.text


def test_bare_mentions_of_names_learned_from_a_resource_id_are_swapped(tmp_path: Path) -> None:
    source = (
        f"target: {_ARM}Microsoft.Web/sites/nordbro-web-app\n"
        "description: 5xx rate high on nordbro-web-app. Group NORDBRO-PRD-RG is shared."
    )
    result = sanitize(source, load_policy(), Vault(b"key", tmp_path / "vault.json"))
    assert "nordbro" not in result.text.lower()
    site_alias = result.text.split("/sites/")[1].split("\n")[0]
    assert f"on {site_alias}." in result.text


def test_names_from_a_preloaded_case_mapping_are_swapped_in_new_text(tmp_path: Path) -> None:
    first = sanitize(
        f"{_ARM}Microsoft.Web/sites/nordbro-web-app",
        load_policy(),
        Vault(b"key", tmp_path / "a.json"),
    )
    evidence = sanitize(
        "error: nordbro-web-app returned 503",
        load_policy(),
        Vault(b"other", tmp_path / "b.json", initial_pairs=first.mapping),
    )
    assert "nordbro-web-app" not in evidence.text
    alias = next(s for s, o in first.mapping.items() if o == "nordbro-web-app")
    assert evidence.text == f"error: {alias} returned 503"


def test_known_names_are_not_replaced_inside_longer_tokens(tmp_path: Path) -> None:
    first = sanitize(
        f"{_ARM}Microsoft.Web/sites/nordbro-web-app",
        load_policy(),
        Vault(b"key", tmp_path / "a.json"),
    )
    evidence = sanitize(
        "see nordbro-web-app-staging-copy and xnordbro-web-app",
        load_policy(),
        Vault(b"other", tmp_path / "b.json", initial_pairs=first.mapping),
    )
    vault_hits = [f for f in evidence.findings if f.detector == "vault"]
    assert vault_hits == []
