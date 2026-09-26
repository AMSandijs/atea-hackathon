"""Copilot-requested read: MCP request -> local queue -> GUI approvals -> MCP evidence.

The planner and the Azure adapter are mocked; no model or tenant is contacted.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from mcp import Client

from airlock import azure, investigation
from airlock.azure import AzureReadError
from airlock.cases import prepare_case
from airlock.config import load_policy
from airlock.handoff import RequestSupervisor, request_status
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
SECRET_RESULT = "STORAGE_KEY=Xo9vK2mA7pQ1sR4tU6wY8zB0cD3eF5gH"
FORBIDDEN = ("nordbro", "qconv", "11111111-2222", "/subscriptions/", "Xo9vK2mA7pQ1")


@pytest.fixture
def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AIRLOCK_CASE_DIR", str(tmp_path))
    monkeypatch.delenv("AIRLOCK_LOCAL_MODEL_URL", raising=False)
    case_id = prepare_case(
        "host: nordbro-rmq-prd.westeurope.cloudapp.azure.com",
        load_policy(),
        tmp_path,
        decision=True,
        allow_rules_only=True,
    )
    assert case_id is not None
    create_case_scope(
        case_id, {"VM_1": CASE_RESOURCE}, approve_scope=lambda _: True, directory=tmp_path
    )
    supervisor = RequestSupervisor(tmp_path, started_at=datetime.now(UTC) - timedelta(seconds=1))
    calls: list[object] = []
    monkeypatch.setattr(
        azure, "_execute_authorized_read", lambda read: calls.append(read) or RAW_RESULT
    )
    return tmp_path, case_id, supervisor, calls


def _mcp(tool: str, arguments: dict[str, object]) -> object:
    async def run() -> object:
        async with Client(mcp) as client:
            result = await client.call_tool(tool, arguments)
            assert result.is_error is False, result
            if result.structured_content is not None and tool != "read_evidence":
                return result.structured_content
            return "".join(getattr(item, "text", "") for item in result.content)

    return asyncio.run(run())


def _request(case_id: str, monkeypatch: pytest.MonkeyPatch, proposal: QueryProposal) -> str:
    monkeypatch.setattr(investigation, "plan_query", lambda *_: proposal)
    response = _mcp("request_investigation", {"case_id": case_id, "goal": "Check VM_1 CPU"})
    assert response["status"] == "queued", response
    return response["request_id"]


def _vm_cpu() -> QueryProposal:
    return QueryProposal(operation="vm_cpu", target_alias="VM_1", time_range_minutes=60)


def _run(supervisor, record, directory, *, query=True, result=True, on_query=None):
    reviews: dict[str, list[object]] = {"query": [], "result": []}

    def approve_query(review) -> bool:
        reviews["query"].append(review)
        if on_query is not None:
            on_query()
        return query

    def approve_result(raw: str, sanitized: Sanitized) -> bool:
        reviews["result"].append((raw, sanitized))
        return result

    status = investigation.run_queued_request(
        supervisor,
        record,
        load_policy(),
        approve_query=approve_query,
        approve_result=approve_result,
        allow_rules_only=True,
        directory=directory,
    )
    return status, reviews


def _queue_text(directory: Path) -> str:
    return "".join(p.read_text(encoding="utf-8") for p in (directory / "requests").glob("*.json"))


def test_copilot_request_runs_one_approved_read_and_mcp_reads_only_sanitized_evidence(
    setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory, case_id, supervisor, calls = setup
    request_id = _request(case_id, monkeypatch, _vm_cpu())
    observed = [_mcp("investigation_status", {"case_id": case_id, "request_id": request_id})]

    record = supervisor.claim_next(case_id)
    assert record is not None and record.request_id == request_id
    states: list[str] = []

    def during_query() -> None:
        states.append(request_status(case_id, request_id, directory)["status"])

    status, reviews = _run(supervisor, record, directory, on_query=during_query)

    assert status == "released"
    assert states == ["awaiting_query_approval"]
    assert len(calls) == 1
    assert reviews["query"][0].resource_id == CASE_RESOURCE  # real target shown locally
    assert reviews["result"][0][0] == RAW_RESULT  # raw shown locally only
    final = _mcp("investigation_status", {"case_id": case_id, "request_id": request_id})
    assert final["status"] == "released"
    evidence = _mcp("read_evidence", {"case_id": case_id, "evidence_id": final["evidence_id"]})
    assert "97" in evidence
    for _ in range(3):
        observed.append(
            _mcp("investigation_status", {"case_id": case_id, "request_id": request_id})
        )
    assert len(calls) == 1  # polling never reruns work

    cloud_visible = json.dumps(observed + [final]) + str(evidence) + _queue_text(directory)
    for forbidden in FORBIDDEN:
        assert forbidden not in cloud_visible
    assert supervisor.claim_next(case_id) is None  # single use


def test_query_denial_means_zero_adapter_calls(setup, monkeypatch) -> None:
    directory, case_id, supervisor, calls = setup
    request_id = _request(case_id, monkeypatch, _vm_cpu())
    status, reviews = _run(supervisor, supervisor.claim_next(case_id), directory, query=False)
    assert status == "denied"
    assert calls == [] and reviews["result"] == []
    assert request_status(case_id, request_id, directory) == {"status": "denied"}


def test_result_denial_releases_no_evidence(setup, monkeypatch) -> None:
    directory, case_id, supervisor, calls = setup
    request_id = _request(case_id, monkeypatch, _vm_cpu())
    status, _ = _run(supervisor, supervisor.claim_next(case_id), directory, result=False)
    assert status == "denied"
    assert len(calls) == 1
    assert request_status(case_id, request_id, directory) == {"status": "denied"}
    assert not list(directory.glob(f"{case_id}.evidence-*.json"))


def test_block_tier_result_cannot_be_released_even_if_callback_approves(setup, monkeypatch) -> None:
    directory, case_id, supervisor, calls = setup
    monkeypatch.setattr(
        azure, "_execute_authorized_read", lambda read: calls.append(read) or SECRET_RESULT
    )
    request_id = _request(case_id, monkeypatch, _vm_cpu())
    status, reviews = _run(supervisor, supervisor.claim_next(case_id), directory, result=True)
    assert status == "blocked"
    assert reviews["result"][0][1].blocked
    assert request_status(case_id, request_id, directory) == {"status": "blocked"}
    assert not list(directory.glob(f"{case_id}.evidence-*.json"))
    assert "Xo9vK2mA7pQ1" not in _queue_text(directory)


def test_forged_out_of_scope_record_is_rejected_by_broker(setup, monkeypatch) -> None:
    directory, case_id, supervisor, calls = setup
    request_id = _request(case_id, monkeypatch, _vm_cpu())
    path = directory / "requests" / f"{case_id}.req-{request_id}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["proposal"]["target_alias"] = "VM_9"  # valid shape, not in the approved scope
    path.write_text(json.dumps(data), encoding="utf-8")

    record = supervisor.claim_next(case_id)
    assert record is not None
    status, reviews = _run(supervisor, record, directory)
    assert status == "rejected"
    assert calls == [] and reviews["query"] == []


def test_azure_failure_after_approval_is_failed_not_rejected(setup, monkeypatch) -> None:
    directory, case_id, supervisor, _ = setup

    def broken(_read: object) -> str:
        raise AzureReadError("az failed for nordbro-vm")

    monkeypatch.setattr(azure, "_execute_authorized_read", broken)
    request_id = _request(case_id, monkeypatch, _vm_cpu())
    status, _ = _run(supervisor, supervisor.claim_next(case_id), directory)
    assert status == "failed"
    assert request_status(case_id, request_id, directory) == {"status": "failed"}


def test_request_reached_after_deadline_asks_nothing(setup, monkeypatch) -> None:
    directory, case_id, supervisor, calls = setup
    request_id = _request(case_id, monkeypatch, _vm_cpu())
    record = supervisor.claim_next(case_id)
    monkeypatch.setattr(
        investigation, "_now", lambda: record.deadline_at + timedelta(seconds=1)
    )  # the operator reaches the request only after its deadline
    status, reviews = _run(supervisor, record, directory)
    assert status == "expired"
    assert calls == [] and reviews["query"] == [] and reviews["result"] == []
    assert not list(directory.glob(f"{case_id}.evidence-*.json"))
    assert request_status(case_id, request_id, directory)["status"] == "expired"


def test_deadline_passing_during_azure_read_releases_nothing(setup, monkeypatch) -> None:
    directory, case_id, supervisor, calls = setup
    request_id = _request(case_id, monkeypatch, _vm_cpu())
    record = supervisor.claim_next(case_id)
    clock = {"now": datetime.now(UTC)}
    monkeypatch.setattr(investigation, "_now", lambda: clock["now"])

    def slow_read(read: object) -> str:
        calls.append(read)
        clock["now"] = record.deadline_at + timedelta(seconds=1)
        return RAW_RESULT

    monkeypatch.setattr(azure, "_execute_authorized_read", slow_read)
    status, reviews = _run(supervisor, record, directory)
    assert status == "expired"
    assert len(calls) == 1 and reviews["result"] == []
    assert not list(directory.glob(f"{case_id}.evidence-*.json"))
    assert request_status(case_id, request_id, directory) == {"status": "expired"}


def test_gui_shutdown_during_query_review_prevents_the_read(setup, monkeypatch) -> None:
    directory, case_id, supervisor, calls = setup
    request_id = _request(case_id, monkeypatch, _vm_cpu())
    record = supervisor.claim_next(case_id)
    status, _ = _run(supervisor, record, directory, query=True, on_query=supervisor.shutdown)
    assert status == "cancelled"
    assert calls == []
    assert request_status(case_id, request_id, directory) == {"status": "cancelled"}


def test_gui_shutdown_during_azure_read_releases_nothing(setup, monkeypatch) -> None:
    directory, case_id, supervisor, calls = setup
    request_id = _request(case_id, monkeypatch, _vm_cpu())
    record = supervisor.claim_next(case_id)

    def read_then_close(read: object) -> str:
        calls.append(read)
        supervisor.shutdown()
        return RAW_RESULT

    monkeypatch.setattr(azure, "_execute_authorized_read", read_then_close)
    status, reviews = _run(supervisor, record, directory)
    assert status == "cancelled"
    assert len(calls) == 1 and reviews["result"] == []
    assert not list(directory.glob(f"{case_id}.evidence-*.json"))
    assert request_status(case_id, request_id, directory) == {"status": "cancelled"}


def test_expired_scope_is_rejected_without_a_read(setup, monkeypatch) -> None:
    directory, case_id, supervisor, calls = setup
    _request(case_id, monkeypatch, _vm_cpu())
    record = supervisor.claim_next(case_id)
    scope_path = directory / f"{case_id}.scope.json"
    scope = json.loads(scope_path.read_text(encoding="utf-8"))
    scope["created_at"] = "2026-01-01T00:00:00Z"
    scope["expires_at"] = "2026-01-01T01:00:00Z"
    scope_path.write_text(json.dumps(scope), encoding="utf-8")
    status, reviews = _run(supervisor, record, directory)
    assert status == "rejected"
    assert calls == [] and reviews["query"] == []


def test_result_approved_after_deadline_is_not_released(setup, monkeypatch) -> None:
    directory, case_id, supervisor, calls = setup
    request_id = _request(case_id, monkeypatch, _vm_cpu())
    record = supervisor.claim_next(case_id)
    clock = {"now": datetime.now(UTC)}
    monkeypatch.setattr(investigation, "_now", lambda: clock["now"])

    def slow_operator(_raw: str, _sanitized: Sanitized) -> bool:
        clock["now"] = record.deadline_at + timedelta(seconds=1)
        return True

    status = investigation.run_queued_request(
        supervisor,
        record,
        load_policy(),
        approve_query=lambda _: True,
        approve_result=slow_operator,
        allow_rules_only=True,
        directory=directory,
    )
    assert status == "expired"
    assert len(calls) == 1
    assert not list(directory.glob(f"{case_id}.evidence-*.json"))
    assert request_status(case_id, request_id, directory) == {"status": "expired"}


def test_query_approved_after_deadline_runs_no_read(setup, monkeypatch) -> None:
    directory, case_id, supervisor, calls = setup
    request_id = _request(case_id, monkeypatch, _vm_cpu())
    record = supervisor.claim_next(case_id)
    clock = {"now": datetime.now(UTC)}
    monkeypatch.setattr(investigation, "_now", lambda: clock["now"])

    def late() -> None:
        clock["now"] = record.deadline_at + timedelta(seconds=1)

    status, reviews = _run(supervisor, record, directory, query=True, on_query=late)
    assert status == "expired"
    assert calls == [] and reviews["result"] == []
    assert request_status(case_id, request_id, directory) == {"status": "expired"}


def test_query_review_ui_failure_is_failed_and_runs_no_read(setup, monkeypatch) -> None:
    directory, case_id, supervisor, calls = setup
    request_id = _request(case_id, monkeypatch, _vm_cpu())

    def broken_dialog() -> None:
        raise RuntimeError("dialog crashed")

    status, _ = _run(supervisor, supervisor.claim_next(case_id), directory, on_query=broken_dialog)
    assert status == "failed"
    assert calls == []
    assert request_status(case_id, request_id, directory) == {"status": "failed"}
