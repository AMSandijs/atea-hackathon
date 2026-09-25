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
