"""Azure evidence is persisted and exposed only after local sanitization and approval."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from mcp import Client

from airlock import azure
from airlock.broker import execute_query
from airlock.cases import prepare_case, read_evidence, release_evidence, restore_case
from airlock.config import load_policy
from airlock.mcpserver import mcp
from airlock.planner import QueryProposal
from airlock.scope import create_case_scope


def _approved_case(directory: Path) -> str:
    case_id = prepare_case(
        "host: nordbro-rmq-prd.westeurope.cloudapp.azure.com",
        load_policy(),
        directory,
        decision=True,
        allow_rules_only=True,
    )
    assert case_id is not None
    return case_id


def test_approved_evidence_is_sanitized_and_restorable(tmp_path: Path) -> None:
    case_id = _approved_case(tmp_path)
    original_case = json.loads((tmp_path / f"{case_id}.json").read_text(encoding="utf-8"))["text"]
    case_alias = original_case.split(": ", 1)[1]
    raw = (
        "host: nordbro-rmq-prd.westeurope.cloudapp.azure.com\n"
        "database: qconv-sql-prd.database.windows.net\n"
        "cpu_percent: 97"
    )

    evidence_id = release_evidence(
        case_id, raw, load_policy(), decision=True, allow_rules_only=True, directory=tmp_path
    )

    assert evidence_id is not None
    released = read_evidence(case_id, evidence_id, tmp_path)
    assert case_alias in released
    assert "nordbro" not in released
    assert "qconv" not in released
    assert "97" in released
    public = json.loads(
        (tmp_path / f"{case_id}.evidence-{evidence_id}.json").read_text(encoding="utf-8")
    )
    assert "nordbro" not in json.dumps(public)
    assert "qconv" not in json.dumps(public)

    restored, unmapped = restore_case(case_id, released, tmp_path)
    assert "nordbro-rmq-prd.westeurope.cloudapp.azure.com" in restored
    assert "qconv-sql-prd.database.windows.net" in restored
    assert not unmapped


def test_rejected_or_blocked_evidence_is_not_persisted(tmp_path: Path) -> None:
    case_id = _approved_case(tmp_path)
    assert (
        release_evidence(
            case_id,
            "host: nordbro-rmq-prd.westeurope.cloudapp.azure.com",
            load_policy(),
            decision=False,
            allow_rules_only=True,
            directory=tmp_path,
        )
        is None
    )
    assert (
        release_evidence(
            case_id,
            "STORAGE_KEY=Xo9vK2mA7pQ1sR4tU6wY8zB0cD3eF5gH",
            load_policy(),
            decision=True,
            allow_rules_only=True,
            directory=tmp_path,
        )
        is None
    )
    assert not list(tmp_path.glob(f"{case_id}.evidence-*.json"))
    assert not list(tmp_path.glob(f"{case_id}.evidence-*.map.json"))


def test_query_approval_does_not_approve_result_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case_id = _approved_case(tmp_path)
    create_case_scope(
        case_id,
        {
            "VM_1": "/subscriptions/11111111-2222-3333-4444-555555555555/"
            "resourceGroups/nordbro-rg/providers/Microsoft.Compute/virtualMachines/nordbro-vm"
        },
        approve_scope=lambda _: True,
        directory=tmp_path,
    )
    query_was_approved: list[bool] = []
    monkeypatch.setattr(azure, "_execute_authorized_read", lambda _: '{"cpu_percent":97}')
    raw_result = execute_query(
        case_id,
        QueryProposal(operation="vm_cpu", target_alias="VM_1", time_range_minutes=30),
        approve_query=lambda _: query_was_approved.append(True) is None,
        directory=tmp_path,
    )
    assert raw_result == '{"cpu_percent":97}'
    assert query_was_approved == [True]

    assert (
        release_evidence(
            case_id,
            raw_result,
            load_policy(),
            decision=False,
            allow_rules_only=True,
            directory=tmp_path,
        )
        is None
    )
    assert not list(tmp_path.glob(f"{case_id}.evidence-*.json"))


def test_evidence_requires_parent_case_model_and_bounded_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case_id = _approved_case(tmp_path)
    monkeypatch.delenv("AIRLOCK_LOCAL_MODEL_URL", raising=False)
    with pytest.raises(ValueError, match="local model is not configured"):
        release_evidence(case_id, "cpu_percent: 97", load_policy(), directory=tmp_path)
    with pytest.raises(ValueError, match="1 MB"):
        release_evidence(
            case_id,
            "x" * (1024 * 1024 + 1),
            load_policy(),
            allow_rules_only=True,
            directory=tmp_path,
        )
    with pytest.raises((OSError, ValueError)):
        release_evidence(
            "0" * 24, "cpu_percent: 97", load_policy(), allow_rules_only=True, directory=tmp_path
        )
    assert not list(tmp_path.glob(f"{case_id}.evidence-*.json"))


def test_evidence_reader_and_mcp_expose_only_approved_sanitized_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AIRLOCK_CASE_DIR", str(tmp_path))
    case_id = _approved_case(tmp_path)
    evidence_id = release_evidence(
        case_id,
        "host: nordbro-rmq-prd.westeurope.cloudapp.azure.com",
        load_policy(),
        decision=True,
        allow_rules_only=True,
        directory=tmp_path,
    )
    assert evidence_id is not None

    async def call_tool() -> str:
        async with Client(mcp) as client:
            result = await client.call_tool(
                "read_evidence", {"case_id": case_id, "evidence_id": evidence_id}
            )
            return str(result)

    response = asyncio.run(call_tool())
    assert "nordbro" not in response
    assert read_evidence(case_id, evidence_id, tmp_path) in response
    with pytest.raises(ValueError, match="invalid case or evidence ID"):
        read_evidence(case_id, "../private", tmp_path)


def test_unapproved_evidence_and_orphan_map_are_not_read_or_restored(tmp_path: Path) -> None:
    case_id = _approved_case(tmp_path)
    evidence_id = "a" * 24
    public = tmp_path / f"{case_id}.evidence-{evidence_id}.json"
    private_map = tmp_path / f"{case_id}.evidence-{evidence_id}.map.json"
    public.write_text(
        json.dumps(
            {"case_id": case_id, "evidence_id": evidence_id, "approved": False, "text": "no"}
        )
    )
    private_map.write_text(json.dumps({"mapping": {"alias-private": "real-private-name"}}))
    with pytest.raises(ValueError, match="not approved"):
        read_evidence(case_id, evidence_id, tmp_path)
    restored, unmapped = restore_case(case_id, "alias-private", tmp_path)
    assert restored == "alias-private"
    assert "real-private-name" not in restored
    assert not unmapped


def test_checkpoint_failure_leaves_no_evidence_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from airlock import cases

    case_id = _approved_case(tmp_path)

    def fail_checkpoint(*args: object, **kwargs: object) -> bool:
        raise RuntimeError("approval UI unavailable")

    monkeypatch.setattr(cases, "checkpoint", fail_checkpoint)
    with pytest.raises(RuntimeError, match="approval UI unavailable"):
        release_evidence(
            case_id,
            "host: nordbro-rmq-prd.westeurope.cloudapp.azure.com",
            load_policy(),
            allow_rules_only=True,
            directory=tmp_path,
        )
    assert not list(tmp_path.glob(f"{case_id}.evidence-*.json"))
    assert not list(tmp_path.glob(f"{case_id}.evidence-*.map.json"))
