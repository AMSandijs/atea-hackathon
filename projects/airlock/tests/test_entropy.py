from airlock.config import load_policy
from airlock.detect.entropy import detect, shannon_entropy


def test_entropy_flags_unknown_long_token_but_allows_uuid_and_sha() -> None:
    secret = "aZ7mQ2vL9xR4kP8nT6yW3cH5jS1dF0gB"
    text = f"secret={secret} uuid=8f4c2b91-3d07-4a1e-b8c2-77e3a9d61f04 sha={'a' * 40}"
    findings = detect(text, load_policy())
    assert [finding.text for finding in findings] == [secret]
    assert shannon_entropy(secret) > 3.6


def test_entropy_ignores_low_entropy_tokens_and_short_values() -> None:
    text = "value=" + ("a" * 32) + " short=aZ7mQ2vL9xR4"
    assert detect(text, load_policy()) == []


def test_entropy_does_not_treat_azure_resource_path_as_one_secret() -> None:
    resource_id = (
        "/subscriptions/8f4c2b91-3d07-4a1e-b8c2-77e3a9d61f04/"
        "resourceGroups/nordbro-prd-rg/providers/Microsoft.Compute/virtualMachines/qconv-vm-prd"
    )
    assert detect(resource_id, load_policy()) == []


NAMING_CONVENTION = [
    "nordbro-checkout-ai-prd",
    "contoso-payments-api-prd",
    "fabrikam-webshop-prd-weu-01",
    "kv-nordbro-shared-weu-001",
    "st-nordbro-logs-weu-001",
    "vnet-hub-westeurope-001",
    "sqldb-orders-prd-weu-001",
    "physical_data_read_percent",
]


def test_naming_convention_names_are_not_unknown_secrets() -> None:
    policy = load_policy()
    for name in NAMING_CONVENTION:
        assert detect(f"resource {name} failed", policy) == [], name
        resource_id = (
            "/subscriptions/8f4c2b91-3d07-4a1e-b8c2-77e3a9d61f04/resourceGroups/"
            f"rg-{name}/providers/Microsoft.Web/sites/{name}"
        )
        assert detect(resource_id, policy) == [], name


def test_secret_shapes_with_separators_or_lowercase_are_still_flagged() -> None:
    policy = load_policy()
    for secret in (
        "x7k2m9p4q8r3-t6w1y5z0v8u2",  # random lowercase alphanumeric segments
        "sk-live-4f9a8b7c6d5e4f3a2b1c0d9e",  # vendor-style key with a hex body
        "9f86d081884c7d659a2feaa0c55ad015",  # 32-char lowercase hex
        "Prod-Token-aZ7mQ2vL9xR4kP8n",  # mixed case
    ):
        found = [finding.text for finding in detect(f"token={secret}", policy)]
        assert found == [secret], secret
