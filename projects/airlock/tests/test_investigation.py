"""The CLI supervisor composes one locally approved read and evidence release."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from mcp import Client
from typer.testing import CliRunner

from airlock import azure, investigation
from airlock.broker import BrokerError
from airlock.cases import prepare_case, read_evidence
from airlock.cli import app
from airlock.config import load_policy
from airlock.mcpserver import mcp
from airlock.models import Sanitized
from airlock.planner import QueryProposal
from airlock.scope import create_case_scope

CASE_RESOURCE = (
    "/subscriptions/11111111-2222-3333-4444-555555555555/"
    "resourceGroups/nordbro-rg/providers/Microsoft.Compute/virtualMachines/nordbro-vm"
)
RAW_RESULT = json.dumps(
    {
        "resource": "nordbro-rmq-prd.westeurope.cloudapp.azure.com",
        "database": "qconv-sql-prd.database.windows.net",
        "cpu_percent": 97,
    }
)


def _case_with_scope(directory: Path) -> str:
    case_id = prepare_case(
        "host: nordbro-rmq-prd.westeurope.cloudapp.azure.com",
        load_policy(),
        directory,
        decision=True,
        allow_rules_only=True,
    )
    assert case_id is not None
    create_case_scope(
        case_id,
        {"VM_1": CASE_RESOURCE},
        approve_scope=lambda _: True,
        directory=directory,
    )
    return case_id


def _proposal(operation: str = "vm_cpu", target: str = "VM_1") -> QueryProposal:
    return QueryProposal(operation=operation, target_alias=target, time_range_minutes=60)


def test_supervised_turn_releases_only_sanitized_mcp_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case_id = _case_with_scope(tmp_path)
    monkeypatch.delenv("AIRLOCK_LOCAL_MODEL_URL", raising=False)
    monkeypatch.setattr(investigation, "plan_query", lambda *_: _proposal())
    executed: list[object] = []
    monkeypatch.setattr(
        azure, "_execute_authorized_read", lambda read: executed.append(read) or RAW_RESULT
    )
    reviews: list[object] = []

    turn = investigation.run_investigation_turn(
        case_id,
        "Inspect VM_1 CPU and adjacent database activity",
        load_policy(),
        approve_query=lambda review: reviews.append(review) is None,
        result_decision=True,
        allow_rules_only=True,
        directory=tmp_path,
    )

    assert turn.status == "released"
    assert turn.evidence_id is not None
    assert len(executed) == 1
    assert len(reviews) == 1
    assert reviews[0].resource_id == CASE_RESOURCE
    sanitized = read_evidence(case_id, turn.evidence_id, tmp_path)
    assert "nordbro" not in sanitized
    assert "qconv" not in sanitized
    assert "97" in sanitized

    async def read_with_mcp() -> str:
        async with Client(mcp) as client:
            result = await client.call_tool(
                "read_evidence", {"case_id": case_id, "evidence_id": turn.evidence_id}
            )
            return str(result)

    monkeypatch.setenv("AIRLOCK_CASE_DIR", str(tmp_path))
    cloud_visible = asyncio.run(read_with_mcp())
    assert "nordbro" not in cloud_visible
    assert "qconv" not in cloud_visible
    assert "97" in cloud_visible


def test_supervised_turn_uses_local_result_review_callback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case_id = _case_with_scope(tmp_path)
    monkeypatch.delenv("AIRLOCK_LOCAL_MODEL_URL", raising=False)
    monkeypatch.setattr(investigation, "plan_query", lambda *_: _proposal())
    monkeypatch.setattr(azure, "_execute_authorized_read", lambda _: RAW_RESULT)
    reviews: list[tuple[str, Sanitized]] = []

    def approve_result(raw: str, sanitized: Sanitized) -> bool:
        reviews.append((raw, sanitized))
        return True

    turn = investigation.run_investigation_turn(
        case_id,
        "Inspect VM_1 CPU and adjacent database activity",
        load_policy(),
        approve_query=lambda _: True,
        approve_result=approve_result,
        allow_rules_only=True,
        directory=tmp_path,
    )

    assert turn.status == "released"
    assert len(reviews) == 1
    assert reviews[0][0] == RAW_RESULT
    assert "nordbro" not in reviews[0][1].text
    assert "qconv" not in reviews[0][1].text


@pytest.mark.parametrize(
    ("proposal", "query_approval", "result_approval", "expected_status", "should_execute"),
    [
        (_proposal("reject", "NONE"), True, True, "proposal_rejected", False),
        (_proposal(), False, True, "query_denied", False),
        (_proposal(), True, False, "result_not_released", True),
    ],
)
def test_rejected_or_denied_turn_never_releases_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    proposal: QueryProposal,
    query_approval: bool,
    result_approval: bool,
    expected_status: str,
    should_execute: bool,
) -> None:
    case_id = _case_with_scope(tmp_path)
    monkeypatch.delenv("AIRLOCK_LOCAL_MODEL_URL", raising=False)
    monkeypatch.setattr(investigation, "plan_query", lambda *_: proposal)
    calls: list[object] = []
    monkeypatch.setattr(
        azure, "_execute_authorized_read", lambda read: calls.append(read) or RAW_RESULT
    )

    turn = investigation.run_investigation_turn(
        case_id,
        "Inspect VM_1 CPU",
        load_policy(),
        approve_query=lambda _: query_approval,
        result_decision=result_approval,
        allow_rules_only=True,
        directory=tmp_path,
    )

    assert turn.status == expected_status
    assert (len(calls) == 1) is should_execute
    assert turn.evidence_id is None
    assert not list(tmp_path.glob(f"{case_id}.evidence-*.json"))


def test_cli_scope_and_investigate_run_with_separate_local_approvals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case_id = prepare_case(
        "host: nordbro-rmq-prd.westeurope.cloudapp.azure.com",
        load_policy(),
        tmp_path,
        decision=True,
        allow_rules_only=True,
    )
    assert case_id is not None
    monkeypatch.setenv("AIRLOCK_CASE_DIR", str(tmp_path))
    monkeypatch.delenv("AIRLOCK_LOCAL_MODEL_URL", raising=False)
    runner = CliRunner()
    scoped = runner.invoke(
        app,
        ["scope", case_id, "--alias", "VM_1"],
        input=f"{CASE_RESOURCE}\ny\n",
    )
    assert scoped.exit_code == 0, scoped.output
    assert "nordbro-vm" in scoped.output

    monkeypatch.setattr(investigation, "plan_query", lambda *_: _proposal())
    monkeypatch.setattr(azure, "_execute_authorized_read", lambda _: RAW_RESULT)
    investigated = runner.invoke(
        app,
        ["investigate", case_id, "--goal", "Inspect VM_1 CPU over the last hour", "--rules-only"],
        input="y\ny\n",
    )
    assert investigated.exit_code == 0, investigated.output
    assert "evidence_id=" in investigated.output
    assert "Approve and save" not in investigated.output
    assert "Approve transmission?" in investigated.output


def test_cli_scope_rejection_persists_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case_id = prepare_case(
        "host: nordbro-rmq-prd.westeurope.cloudapp.azure.com",
        load_policy(),
        tmp_path,
        decision=True,
        allow_rules_only=True,
    )
    assert case_id is not None
    monkeypatch.setenv("AIRLOCK_CASE_DIR", str(tmp_path))
    result = CliRunner().invoke(
        app,
        ["scope", case_id, "--alias", "VM_1"],
        input=f"{CASE_RESOURCE}\nn\n",
    )
    assert result.exit_code == 2
    assert not (tmp_path / f"{case_id}.scope.json").exists()


def test_plan_investigation_uses_only_case_capabilities_and_never_reads_azure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case_id = _case_with_scope(tmp_path)
    seen: list[tuple[str, dict[str, tuple[str, ...]]]] = []

    def fake_plan(goal: str, capabilities: dict[str, tuple[str, ...]], _policy: object):
        seen.append((goal, dict(capabilities)))
        return _proposal()

    monkeypatch.setattr(investigation, "plan_query", fake_plan)
    monkeypatch.setattr(
        azure, "_execute_authorized_read", lambda _: pytest.fail("planning must not read Azure")
    )

    proposal = investigation.plan_investigation(
        case_id, "Inspect VM_1 CPU", load_policy(), directory=tmp_path
    )

    assert proposal == _proposal()
    assert seen == [("Inspect VM_1 CPU", {"VM_1": ("vm_cpu",)})]
    assert CASE_RESOURCE not in repr(seen)


def test_run_investigation_proposal_revalidates_untrusted_proposal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case_id = _case_with_scope(tmp_path)
    calls: list[object] = []
    monkeypatch.setattr(
        azure, "_execute_authorized_read", lambda read: calls.append(read) or RAW_RESULT
    )
    forged = QueryProposal.model_construct(
        operation="vm_cpu", target_alias="VM_9", time_range_minutes=60
    )

    with pytest.raises(BrokerError):
        investigation.run_investigation_proposal(
            case_id,
            forged,
            load_policy(),
            approve_query=lambda _: True,
            result_decision=True,
            allow_rules_only=True,
            directory=tmp_path,
        )
    assert calls == []


def test_run_investigation_proposal_releases_one_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case_id = _case_with_scope(tmp_path)
    monkeypatch.delenv("AIRLOCK_LOCAL_MODEL_URL", raising=False)
    calls: list[object] = []
    monkeypatch.setattr(
        azure, "_execute_authorized_read", lambda read: calls.append(read) or RAW_RESULT
    )

    turn = investigation.run_investigation_proposal(
        case_id,
        _proposal(),
        load_policy(),
        approve_query=lambda _: True,
        result_decision=True,
        allow_rules_only=True,
        directory=tmp_path,
    )

    assert turn.status == "released"
    assert len(calls) == 1
