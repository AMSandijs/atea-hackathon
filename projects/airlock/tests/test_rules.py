from airlock.config import load_policy
from airlock.detect.rules import detect


def _types(text: str) -> set[str]:
    return {finding.entity_type for finding in detect(text, load_policy())}


def test_detects_structured_customer_identifiers_and_secrets() -> None:
    text = (
        "/subscriptions/8f4c2b91-3d07-4a1e-b8c2-77e3a9d61f04/"
        "resourceGroups/nordbro-prd-rg/providers/Microsoft.Web/sites/qconv-inhouse-prd\n"
        "host: nordbro-rmq-prd.westeurope.cloudapp.azure.com\n"
        "public: 203.0.113.7\n"
        "IBAN: LV80 BANK 0000 1234 5678 9\n"
        "owner: Lars Olesen\n"
        "mail: lars.olesen@nordbro.dk\n"
        "STORAGE_KEY=Xo9vK2mA7pQ1sR4tU6wY8zB0cD3eF5gH\n"
        "url=https://blob.example.invalid/file?sv=2026-01-01&se=2026-12-31&sig=abc123"
    )
    found = detect(text, load_policy())
    types = {finding.entity_type for finding in found}
    assert {"AZURE_RESOURCE_ID", "AZURE_SUBSCRIPTION_ID", "AZURE_RESOURCE_NAME"} <= types
    assert {"HOSTNAME", "PUBLIC_IP", "IBAN", "EMAIL_ADDRESS", "SECRET_KEY", "SAS_TOKEN"} <= types
    assert all(text[finding.start : finding.end] == finding.text for finding in found)


def test_rejects_bad_checksums_and_private_addresses() -> None:
    text = "bad IBAN LV81 BANK 0000 1234 5678 9; private 10.0.0.4; loopback 127.0.0.1"
    types = _types(text)
    assert "IBAN" not in types
    assert "PUBLIC_IP" not in types


def test_validates_latvian_and_danish_personal_code_shapes() -> None:
    types = _types("LV 010190-10000 DK 010100-1234")
    assert "NATIONAL_ID_LV" in types
    assert "NATIONAL_ID_DK" in types
    assert "NATIONAL_ID_LV" not in _types("LV 321390-10000")


def test_resource_id_stops_before_nested_metrics_extension() -> None:
    from airlock.config import load_policy
    from airlock.detect.rules import detect

    base = (
        "/subscriptions/8f4c2b91-3d07-4a1e-b8c2-77e3a9d61f04/resourceGroups/nordbro-rg/providers/"
    )
    cases = {
        base + "microsoft.insights/components/nordbro-web-ai/providers/Microsoft.Insights/"
        "metrics/requests/failed": base + "microsoft.insights/components/nordbro-web-ai",
        base + "Microsoft.Compute/virtualMachines/nordbro-vm1/providers/Microsoft.Insights/"
        "metrics/Percentage CPU": base + "Microsoft.Compute/virtualMachines/nordbro-vm1",
        base + "Microsoft.Sql/servers/nordbro-sql/databases/orders": base
        + "Microsoft.Sql/servers/nordbro-sql/databases/orders",
    }
    for text, expected in cases.items():
        ids = [f.text for f in detect(text, load_policy()) if f.entity_type == "AZURE_RESOURCE_ID"]
        assert ids == [expected]
