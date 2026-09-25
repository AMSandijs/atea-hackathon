from airlock.models import AirlockResult, Finding, Sanitized


def test_core_models_can_be_constructed() -> None:
    finding = Finding("HOSTNAME", "demo.example", 0, 12, "rules", 0.99)
    sanitized = Sanitized("[HOST]", [finding], {"[HOST]": "demo.example"}, [], [])
    result = AirlockResult("answer", sanitized, "sent", "received", [])
    assert result.sanitized.findings[0].entity_type == "HOSTNAME"
