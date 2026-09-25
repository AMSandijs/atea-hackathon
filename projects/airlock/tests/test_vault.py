import uuid
from pathlib import Path

from airlock.models import Finding
from airlock.vault import Vault


def finding(entity_type: str, text: str) -> Finding:
    return Finding(entity_type, text, 0, len(text), "rules", 1.0)


def test_vault_is_deterministic_and_persisted_without_key(tmp_path: Path) -> None:
    path = tmp_path / "vault.json"
    first = Vault(b"test-key", path)
    original = "8f4c2b91-3d07-4a1e-b8c2-77e3a9d61f04"
    stand_in = first.stand_in(finding("AZURE_SUBSCRIPTION_ID", original))
    first.save()
    second = Vault(b"test-key", path)
    assert second.stand_in(finding("AZURE_SUBSCRIPTION_ID", original)) == stand_in
    assert second.original(stand_in) == original
    assert b"test-key" not in path.read_bytes()


def test_generators_preserve_required_shapes(tmp_path: Path) -> None:
    vault = Vault(b"shape-key", tmp_path / "vault.json")
    generated_uuid = vault.stand_in(finding("AZURE_TENANT_ID", "12345678-1234-4234-8234-123456789012"))
    generated_ip = vault.stand_in(finding("PUBLIC_IP", "203.0.113.7"))
    generated_host = vault.stand_in(finding("HOSTNAME", "nordbro-rmq-prd.westeurope.cloudapp.azure.com"))
    generated_iban = vault.stand_in(finding("IBAN", "LV80 BANK 0000 1234 5678 9"))
    assert uuid.UUID(generated_uuid).version == 4
    assert generated_ip.split(".")[:3] in (["192", "0", "2"], ["198", "51", "100"])
    assert generated_host.endswith("westeurope.cloudapp.azure.com")
    assert len(generated_host.split(".")) == 5
    assert "-rmq-prd." in generated_host
    compact = generated_iban.replace(" ", "")
    moved = compact[4:] + compact[:4]
    numeric = "".join(str(ord(char) - 55) if char.isalpha() else char for char in moved)
    assert int(numeric) % 97 == 1


def test_reverse_lookup_round_trips_multiple_entity_types(tmp_path: Path) -> None:
    vault = Vault(b"round-trip", tmp_path / "vault.json")
    pairs = [
        ("HOSTNAME", "nordbro-rmq-prd.westeurope.cloudapp.azure.com"),
        ("AZURE_RESOURCE_NAME", "qconv-inhouse-prd"),
        ("ORG_NAME", "Nordbro"),
        ("PERSON", "Lars Olesen"),
        ("EMAIL_ADDRESS", "lars.olesen@nordbro.dk"),
        ("NATIONAL_ID_LV", "010190-10000"),
        ("NATIONAL_ID_DK", "010100-1234"),
    ]
    for entity_type, original in pairs:
        stand_in = vault.stand_in(finding(entity_type, original))
        assert vault.original(stand_in) == original


def test_non_structural_resource_segments_and_customer_domain_are_hidden(tmp_path: Path) -> None:
    vault = Vault(b"private-parts", tmp_path / "vault.json")
    resource = vault.stand_in(finding("AZURE_RESOURCE_NAME", "qconv-inhouse-prd"))
    hostname = vault.stand_in(finding("HOSTNAME", "api.meridian-logistics.example.com"))
    azure_site = vault.stand_in(finding("HOSTNAME", "qconv.azurewebsites.net"))
    assert "qconv" not in resource
    assert "inhouse" not in resource
    assert resource.endswith("-prd")
    assert hostname.endswith(".invalid")
    assert len(hostname.split(".")) == 4
    assert "meridian" not in hostname
    assert "logistics" not in hostname
    assert "example.com" not in hostname
    assert azure_site.endswith(".azurewebsites.net")
    assert "qconv" not in azure_site


def test_stand_in_never_equals_original_even_for_dictionary_words(tmp_path: Path) -> None:
    vault = Vault(b"dictionary-collision", tmp_path / "vault.json")
    for original in ("Alpha", "Bravo", "Meridian", "Northstar", "Cedar", "Harbor", "Summit", "Orbit"):
        alias = vault.stand_in(finding("ORG_NAME", original))
        assert alias.casefold() != original.casefold()


def test_person_and_org_stand_ins_do_not_reuse_original_fragments(tmp_path: Path) -> None:
    vault = Vault(b"fragment-collision", tmp_path / "vault.json")
    for entity_type, original in (("ORG_NAME", "Meridian Logistics"), ("PERSON", "Mira Voss")):
        alias = vault.stand_in(finding(entity_type, original))
        assert alias.casefold() not in original.casefold()
        assert original.casefold() not in alias.casefold()


def test_resource_id_retains_azure_shape_and_component_aliases(tmp_path: Path) -> None:
    vault = Vault(b"resource-key", tmp_path / "vault.json")
    original = (
        "/subscriptions/8f4c2b91-3d07-4a1e-b8c2-77e3a9d61f04/"
        "resourceGroups/nordbro-prd-rg/providers/Microsoft.Compute/virtualMachines/qconv-vm-prd"
    )
    stand_in = vault.stand_in(finding("AZURE_RESOURCE_ID", original))
    assert stand_in.startswith("/subscriptions/")
    assert "/resourceGroups/" in stand_in
    assert "/providers/Microsoft.Compute/virtualMachines/" in stand_in
    assert "nordbro" not in stand_in
    assert "qconv" not in stand_in
    assert vault.original(stand_in) == original
    aliases = vault.related_pairs(finding("AZURE_RESOURCE_ID", original))
    assert "qconv-vm-prd" in aliases.values()
