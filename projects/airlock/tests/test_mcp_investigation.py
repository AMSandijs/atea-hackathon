"""MCP request/status tools: alias-only input, typed queueing, generic responses."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from mcp import Client

from airlock import investigation
from airlock.cases import prepare_case
from airlock.config import load_policy
from airlock.mcpserver import mcp
from airlock.planner import PlannerError, QueryProposal
from airlock.scope import create_case_scope

CASE_RESOURCE = (
    "/subscriptions/11111111-2222-3333-4444-555555555555/"
    "resourceGroups/nordbro-rg/providers/Microsoft.Compute/virtualMachines/nordbro-vm"
)
GOAL = "Inspect VM_1 CPU for the last hour, marker-goal-text"


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
        case_id, {"VM_1": CASE_RESOURCE}, approve_scope=lambda _: True, directory=directory
    )
    return case_id


def _call(tool: str, arguments: dict[str, object]) -> dict[str, object]:
    async def run() -> dict[str, object]:
        async with Client(mcp) as client:
            result = await client.call_tool(tool, arguments)
            assert result.is_error is False, result
            assert isinstance(result.structured_content, dict)
            return result.structured_content

    return asyncio.run(run())


@pytest.fixture
def case_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("AIRLOCK_CASE_DIR", str(tmp_path))
    return tmp_path


def _queued_files(directory: Path) -> list[Path]:
    queue = directory / "requests"
    return sorted(queue.glob("*.json")) if queue.is_dir() else []


def test_tool_surface_is_narrow() -> None:
    async def names() -> dict[str, set[str]]:
        async with Client(mcp) as client:
            tools = (await client.list_tools()).tools
            return {tool.name: set(tool.input_schema["properties"]) for tool in tools}

    assert asyncio.run(names()) == {
        "read_case": {"case_id"},
        "read_evidence": {"case_id", "evidence_id"},
        "request_investigation": {"case_id", "goal"},
        "investigation_status": {"case_id", "request_id"},
    }


def test_request_queues_one_typed_proposal_without_goal_or_real_ids(
    case_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case_id = _case_with_scope(case_dir)
    planned: list[tuple[str, dict[str, tuple[str, ...]]]] = []

    def fake_plan(goal: str, capabilities: dict[str, tuple[str, ...]], _policy: object):
        planned.append((goal, dict(capabilities)))
        return QueryProposal(operation="vm_cpu", target_alias="VM_1", time_range_minutes=60)

    monkeypatch.setattr(investigation, "plan_query", fake_plan)

    response = _call("request_investigation", {"case_id": case_id, "goal": GOAL})

    assert response["status"] == "queued"
    assert set(response) == {"status", "request_id"}
    assert planned == [(GOAL, {"VM_1": ("vm_cpu",)})]
    files = _queued_files(case_dir)
    assert len(files) == 1
    stored = files[0].read_text(encoding="utf-8")
    assert "marker-goal-text" not in stored
    assert "nordbro" not in stored and "/subscriptions/" not in stored

    status = _call(
        "investigation_status", {"case_id": case_id, "request_id": response["request_id"]}
    )
    assert status == {"status": "queued"}

    again = _call("request_investigation", {"case_id": case_id, "goal": GOAL})
    assert again == {"status": "busy", "request_id": response["request_id"]}
    assert len(_queued_files(case_dir)) == 1


@pytest.mark.parametrize(
    "planner",
    [
        lambda *_: QueryProposal(operation="reject", target_alias="NONE", time_range_minutes=1),
        lambda *_: (_ for _ in ()).throw(PlannerError("model said /subscriptions/x")),
        lambda *_: (_ for _ in ()).throw(RuntimeError("unexpected nordbro-vm")),
    ],
)
def test_rejected_or_failed_planning_queues_nothing_and_is_generic(
    case_dir: Path, monkeypatch: pytest.MonkeyPatch, planner
) -> None:
    case_id = _case_with_scope(case_dir)
    monkeypatch.setattr(investigation, "plan_query", planner)

    response = _call("request_investigation", {"case_id": case_id, "goal": GOAL})

    assert response == {"status": "proposal_rejected"}
    assert _queued_files(case_dir) == []


@pytest.mark.parametrize(
    "case_id",
    ["0" * 24, "../../etc", CASE_RESOURCE, ""],
)
def test_unknown_or_malformed_case_is_rejected_before_planning(
    case_dir: Path, monkeypatch: pytest.MonkeyPatch, case_id: str
) -> None:
    monkeypatch.setattr(investigation, "plan_query", lambda *_: pytest.fail("must not plan"))
    assert _call("request_investigation", {"case_id": case_id, "goal": GOAL}) == {
        "status": "proposal_rejected"
    }
    assert _queued_files(case_dir) == []


def test_case_without_scope_is_rejected(case_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case_id = prepare_case(
        "host: nordbro-rmq-prd.westeurope.cloudapp.azure.com",
        load_policy(),
        case_dir,
        decision=True,
        allow_rules_only=True,
    )
    monkeypatch.setattr(investigation, "plan_query", lambda *_: pytest.fail("must not plan"))
    assert _call("request_investigation", {"case_id": case_id, "goal": GOAL}) == {
        "status": "proposal_rejected"
    }


def test_oversized_goal_is_rejected_before_planning(
    case_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case_id = _case_with_scope(case_dir)
    monkeypatch.setattr(investigation, "plan_query", lambda *_: pytest.fail("must not plan"))
    assert _call("request_investigation", {"case_id": case_id, "goal": "VM_1 " * 1_000}) == {
        "status": "proposal_rejected"
    }


def test_synced_queue_location_reports_supervisor_unavailable(
    case_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case_id = _case_with_scope(case_dir)
    monkeypatch.setattr(
        investigation,
        "plan_query",
        lambda *_: QueryProposal(operation="vm_cpu", target_alias="VM_1", time_range_minutes=60),
    )
    monkeypatch.setenv("OneDrive", str(case_dir))
    assert _call("request_investigation", {"case_id": case_id, "goal": GOAL}) == {
        "status": "supervisor_unavailable"
    }
    assert _queued_files(case_dir) == []


@pytest.mark.parametrize("request_id", ["f" * 24, "../x", CASE_RESOURCE, ""])
def test_status_for_unknown_request_is_generic(case_dir: Path, request_id: str) -> None:
    case_id = _case_with_scope(case_dir)
    assert _call("investigation_status", {"case_id": case_id, "request_id": request_id}) == {
        "status": "unknown"
    }
