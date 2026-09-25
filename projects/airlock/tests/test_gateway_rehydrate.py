from pathlib import Path

import httpx
import pytest

from airlock.config import load_policy
from airlock.gateway import send
from airlock.models import Finding, Sanitized
from airlock.rehydrate import rehydrate


def test_gateway_refuses_blocked_payload() -> None:
    sanitized = Sanitized("secret", [], {}, [Finding("SECRET_KEY", "secret", 0, 6, "rules", 1.0, "block")], [])
    with pytest.raises(ValueError, match="blocked"):
        send(sanitized, load_policy())


def test_gateway_transmits_only_sanitized_text(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from airlock import cli

    captured: dict[str, object] = {}

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        captured["payload"] = kwargs["json"]
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "Reviewed."}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setenv("AIRLOCK_CLOUD_ENDPOINT", "https://example.invalid/chat/completions")
    monkeypatch.setenv("AIRLOCK_LOCAL_MODEL_URL", "http://127.0.0.1:12345/v1/chat/completions")
    monkeypatch.setenv("AIRLOCK_VAULT_PATH", str(tmp_path / "vault.json"))
    monkeypatch.setenv("AIRLOCK_RUN_LOG", str(tmp_path / "runs.jsonl"))
    monkeypatch.setattr(httpx, "post", fake_post)
    cli.run_ask("owner: Lars Olesen", "Investigate owner: Lars Olesen", approval=True)

    payload = captured["payload"]
    assert isinstance(payload, dict)
    transmitted = payload["messages"][0]["content"]
    assert "Lars Olesen" not in transmitted
    assert "Investigate owner:" in transmitted


def test_cloud_gateway_requires_local_model(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from airlock import cli

    monkeypatch.setenv("AIRLOCK_CLOUD_ENDPOINT", "https://example.invalid/chat/completions")
    monkeypatch.delenv("AIRLOCK_LOCAL_MODEL_URL", raising=False)
    monkeypatch.setenv("AIRLOCK_RUN_LOG", str(tmp_path / "runs.jsonl"))

    def fail_post(*args: object, **kwargs: object) -> httpx.Response:
        raise AssertionError("nothing may be sent when the local detector is unconfigured")

    monkeypatch.setattr(httpx, "post", fail_post)
    with pytest.raises(ValueError, match="requires a configured loopback local model"):
        cli.run_ask("Mira from Meridian Logistics reported a CPU spike.", "Investigate", approval=True)
    assert not (tmp_path / "runs.jsonl").exists()


def test_cloud_gateway_aborts_when_local_model_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from airlock import cli

    monkeypatch.setenv("AIRLOCK_CLOUD_ENDPOINT", "https://example.invalid/chat/completions")
    monkeypatch.setenv("AIRLOCK_LOCAL_MODEL_URL", "http://127.0.0.1:12345/v1/chat/completions")
    monkeypatch.setenv("AIRLOCK_VAULT_PATH", str(tmp_path / "vault.json"))
    monkeypatch.setenv("AIRLOCK_RUN_LOG", str(tmp_path / "runs.jsonl"))
    destinations: list[str] = []

    def failed_post(url: str, **kwargs: object) -> httpx.Response:
        destinations.append(url)
        raise httpx.ConnectError("offline", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", failed_post)
    with pytest.raises(RuntimeError, match="case was not released"):
        cli.run_ask("Mira from Meridian Logistics reported a CPU spike.", "Investigate", approval=True)
    assert destinations == ["http://127.0.0.1:12345/v1/chat/completions"]


def test_rehydrate_handles_case_line_break_and_partial_hostname() -> None:
    mapping = {"alpha-rmq-prd.westeurope.cloudapp.azure.com": "nordbro-rmq-prd.westeurope.cloudapp.azure.com"}
    answer = "See ALPHA-RMQ-PRD.WESTEUROPE.CLOUDAPP.AZURE.\nCOM and alpha-rmq-prd."
    rebuilt, unmapped = rehydrate(answer, mapping)
    assert rebuilt.count("nordbro-rmq-prd.westeurope.cloudapp.azure.com") == 1
    assert rebuilt.endswith("nordbro-rmq-prd.")
    assert unmapped == []


def test_rehydrate_leaves_invented_neighbour_and_reports_it() -> None:
    mapping = {"alpha-rmq-prd.westeurope.cloudapp.azure.com": "nordbro-rmq-prd.westeurope.cloudapp.azure.com"}
    rebuilt, unmapped = rehydrate("alpha-rmq-uat.westeurope.cloudapp.azure.com", mapping)
    assert rebuilt == "alpha-rmq-uat.westeurope.cloudapp.azure.com"
    assert unmapped == ["alpha-rmq-uat"]


def test_run_log_contains_no_original_values(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from airlock.cli import run_ask

    monkeypatch.setenv("AIRLOCK_RUN_LOG", str(tmp_path / "runs.jsonl"))
    monkeypatch.setenv("AIRLOCK_VAULT_PATH", str(tmp_path / "vault.json"))
    result = run_ask("owner: Lars Olesen", "summarize", Path(__file__).parents[1] / "policy.yaml", approval=True)
    logged = (tmp_path / "runs.jsonl").read_text(encoding="utf-8")
    assert result.sent != "owner: Lars Olesen"
    assert "owner: Lars Olesen" in result.answer
    assert "Lars Olesen" not in logged
    assert "runs.jsonl" in str(tmp_path / "runs.jsonl")


def test_checkpoint_can_render_and_reject_without_sending(tmp_path: Path) -> None:
    from io import StringIO

    from rich.console import Console

    from airlock.checkpoint import checkpoint
    from airlock.sanitize import sanitize
    from airlock.vault import Vault

    policy = load_policy()
    source = "owner: Lars Olesen"
    sanitized = sanitize(source, policy, Vault(b"checkpoint", tmp_path / "vault.json"))
    output = StringIO()
    approved = checkpoint(source, sanitized, policy, Console(file=output), decision=False)
    assert approved is False
    assert "Airlock checkpoint" in output.getvalue()
    assert "Transmitted text" in output.getvalue()


def test_rejected_request_never_reaches_gateway(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from airlock import cli

    monkeypatch.setenv("AIRLOCK_RUN_LOG", str(tmp_path / "runs.jsonl"))
    monkeypatch.setenv("AIRLOCK_VAULT_PATH", str(tmp_path / "vault.json"))

    def fail_gateway(*args: object, **kwargs: object) -> tuple[str, int]:
        raise AssertionError("gateway must not be called after rejection")

    monkeypatch.setattr(cli, "send", fail_gateway)
    result = cli.run_ask("owner: Lars Olesen", "summarize", approval=False)
    assert result.sent == ""
    assert result.received == ""
