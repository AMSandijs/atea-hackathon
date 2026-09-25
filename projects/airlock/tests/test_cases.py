"""The Copilot tool may see approved sanitized data, never local originals."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest
from mcp import Client, StdioServerParameters
from typer.testing import CliRunner

from airlock.cases import prepare_case, read_case, restore_case
from airlock.cli import app
from airlock.config import load_policy
from airlock.mcpserver import mcp


def test_approved_case_can_be_read_and_restored(tmp_path: Path) -> None:
    source = "owner: Lars Olesen\nhost: nordbro-rmq-prd.westeurope.cloudapp.azure.com"
    case_id = prepare_case(source, load_policy(), tmp_path, decision=True, allow_rules_only=True)
    assert case_id is not None
    sanitized = read_case(case_id, tmp_path)
    assert "Lars Olesen" not in sanitized
    assert "nordbro-rmq-prd" not in sanitized
    public = json.loads((tmp_path / f"{case_id}.json").read_text(encoding="utf-8"))
    assert "Lars Olesen" not in json.dumps(public)
    restored, unmapped = restore_case(case_id, sanitized, tmp_path)
    assert restored == source
    assert unmapped == []


def test_blocked_and_rejected_cases_are_not_persisted(tmp_path: Path) -> None:
    assert prepare_case("owner: Lars Olesen", load_policy(), tmp_path, decision=False, allow_rules_only=True) is None
    assert prepare_case("STORAGE_KEY=Xo9vK2mA7pQ1sR4tU6wY8zB0cD3eF5gH", load_policy(), tmp_path, decision=True, allow_rules_only=True) is None
    assert list(tmp_path.iterdir()) == []


def test_case_id_rejects_paths(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="invalid case ID"):
        read_case("../secret", tmp_path)


def test_mcp_tool_returns_only_approved_sanitized_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIRLOCK_CASE_DIR", str(tmp_path))
    case_id = prepare_case("owner: Lars Olesen", load_policy(), tmp_path, decision=True, allow_rules_only=True)
    assert case_id is not None

    async def call_tool() -> str:
        async with Client(mcp) as client:
            result = await client.call_tool("read_case", {"case_id": case_id})
            return str(result)

    response = asyncio.run(call_tool())
    assert "Lars Olesen" not in response
    assert "owner:" in response


def test_cli_requires_local_model_unless_rules_only_is_explicit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AIRLOCK_LOCAL_MODEL_URL", raising=False)
    monkeypatch.setenv("AIRLOCK_CASE_DIR", str(tmp_path / "cases"))
    sample = Path(__file__).parents[1] / "samples" / "vm-cpu-alert.json"
    runner = CliRunner()
    refused = runner.invoke(app, ["prepare", str(sample)])
    assert refused.exit_code == 2
    assert not (tmp_path / "cases").exists()

    approved = runner.invoke(app, ["prepare", str(sample), "--rules-only"], input="y\n")
    assert approved.exit_code == 0, approved.output
    case_id = approved.output.split("case_id=")[-1].strip()
    text = read_case(case_id, tmp_path / "cases")
    assert "Microsoft.Compute/virtualMachines" in text
    assert "Percentage CPU" in text
    assert "nordbro" not in text


def test_stdio_mcp_process_reads_an_approved_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AIRLOCK_LOCAL_MODEL_URL", raising=False)
    case_id = prepare_case("owner: Lars Olesen", load_policy(), tmp_path, decision=True, allow_rules_only=True)
    assert case_id is not None

    async def call_process() -> str:
        server = StdioServerParameters(
            command=sys.executable,
            args=["-m", "airlock.mcpserver"],
            env={"AIRLOCK_CASE_DIR": str(tmp_path)},
        )
        async with Client(server, read_timeout_seconds=15) as client:
            result = await client.call_tool("read_case", {"case_id": case_id})
            return str(result)

    response = asyncio.run(call_process())
    assert "owner:" in response
    assert "Lars Olesen" not in response


def test_vm_name_in_copilot_answer_restores_locally(tmp_path: Path) -> None:
    sample = Path(__file__).parents[1] / "samples" / "vm-cpu-alert.json"
    case_id = prepare_case(sample.read_text(encoding="utf-8"), load_policy(), tmp_path, decision=True, allow_rules_only=True)
    assert case_id is not None
    sanitized = json.loads(read_case(case_id, tmp_path))
    alias = sanitized["vmName"]
    answer, unmapped = restore_case(case_id, f"CPU rose on {alias} while sqlservr.exe was active.", tmp_path)
    assert "qconv-vm-prd" in answer
    assert "sqlservr.exe" in answer
    assert unmapped == []


def test_model_backed_vm_case_swaps_unkeyed_prose_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AIRLOCK_LOCAL_MODEL_URL", "http://127.0.0.1:1234/v1/chat/completions")
    sample = Path(__file__).parents[1] / "samples" / "vm-cpu-alert-with-prose.json"

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        payload = kwargs["json"]
        chunk = payload["messages"][1]["content"].split("Text:\n", 1)[1]
        entities = [
            {"type": entity_type, "text": value, "score": 0.9}
            for entity_type, value in (("PERSON", "Mira"), ("ORG_NAME", "Meridian Logistics"))
            if value in chunk
        ]
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps({"entities": entities})}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    case_id = prepare_case(sample.read_text(encoding="utf-8"), load_policy(), tmp_path, decision=True)
    assert case_id is not None
    released = read_case(case_id, tmp_path)
    assert all(original not in released for original in ("Mira", "Meridian Logistics", "qconv", "nordbro"))
    aliases = json.loads(released)
    answer, unmapped = restore_case(case_id, f"{aliases['ticketNote']} VM: {aliases['vmName']}", tmp_path)
    assert all(original in answer for original in ("Mira", "Meridian Logistics", "qconv-vm-prd"))
    assert not unmapped
