"""Private scope and deterministic broker authorization fail closed."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from airlock.broker import BrokerError, authorize_query, case_capabilities, execute_query
from airlock.planner import QueryProposal
from airlock.scope import ScopeError, ScopeReview, create_case_scope

CASE_ID = "a1b2c3d4e5f60718293a4b5c"
VM_ID = "/subscriptions/11111111-2222-3333-4444-555555555555/resourceGroups/demo-rg/providers/Microsoft.Compute/virtualMachines/demo-vm"
SQL_ID = "/subscriptions/11111111-2222-3333-4444-555555555555/resourceGroups/demo-rg/providers/Microsoft.Sql/servers/demo-sql/databases/demo-db"
APP_ID = "/subscriptions/11111111-2222-3333-4444-555555555555/resourceGroups/demo-rg/providers/Microsoft.Insights/components/demo-app"
LOGIC_ID = "/subscriptions/11111111-2222-3333-4444-555555555555/resourceGroups/demo-rg/providers/Microsoft.Logic/workflows/demo-flow"


def _approved_case(directory: Path, approved: bool = True) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{CASE_ID}.json").write_text(
        json.dumps({"case_id": CASE_ID, "approved": approved, "text": "sanitized demo evidence"}),
        encoding="utf-8",
    )


def _scope(directory: Path, resource_ids: dict[str, str] | None = None) -> ScopeReview:
    _approved_case(directory)
    captured: list[ScopeReview] = []
    create_case_scope(
        CASE_ID,
        resource_ids or {"VM_1": VM_ID},
        approve_scope=lambda review: captured.append(review) is None,
        directory=directory,
    )
    return captured[0]


def _proposal(operation: str = "vm_cpu", alias: str = "VM_1", minutes: int = 30) -> QueryProposal:
    return QueryProposal(operation=operation, target_alias=alias, time_range_minutes=minutes)


def test_scope_is_separate_from_approved_case_and_capabilities_hide_real_ids(
    tmp_path: Path,
) -> None:
    _scope(tmp_path, {"VM_1": VM_ID, "SQL_1": SQL_ID})
    public_text = (tmp_path / f"{CASE_ID}.json").read_text(encoding="utf-8")
    capabilities = case_capabilities(CASE_ID, tmp_path)

    assert "demo-vm" not in public_text
    assert "demo-sql" not in public_text
    assert "demo-vm" not in repr(capabilities)
    assert "demo-sql" not in repr(capabilities)
    assert capabilities == {"SQL_1": ("sql_metrics",), "VM_1": ("vm_cpu",)}
    assert "demo-vm" in (tmp_path / f"{CASE_ID}.scope.json").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "resource_id",
    [
        "not-an-arm-id",
        "/subscriptions/not-a-guid/resourceGroups/demo-rg/providers/Microsoft.Compute/virtualMachines/demo-vm",
        "/subscriptions/11111111222233334444555555555555/resourceGroups/demo-rg/providers/Microsoft.Compute/virtualMachines/demo-vm",
        "/subscriptions/11111111-2222-3333-4444-555555555555/resourceGroups/demo-rg/providers/Microsoft.Compute/virtualMachines/demo-vm/child/x",
        "/subscriptions/11111111-2222-3333-4444-555555555555/resourceGroups/demo-rg/providers/Microsoft.Compute/disks/demo-vm",
        "/subscriptions/11111111-2222-3333-4444-555555555555/resourceGroups/demo-rg/providers/Microsoft.Compute/virtualMachines/demo-vm/../other",
    ],
)
def test_scope_rejects_invalid_or_unsupported_resource_ids(
    tmp_path: Path, resource_id: str
) -> None:
    _approved_case(tmp_path)
    with pytest.raises(ScopeError, match="invalid or unsupported"):
        create_case_scope(
            CASE_ID, {"VM_1": resource_id}, approve_scope=lambda _: True, directory=tmp_path
        )
    assert not (tmp_path / f"{CASE_ID}.scope.json").exists()


def test_scope_requires_approved_case_and_explicit_local_approval(tmp_path: Path) -> None:
    _approved_case(tmp_path, approved=False)
    with pytest.raises(ScopeError, match="approved sanitized case"):
        create_case_scope(
            CASE_ID, {"VM_1": VM_ID}, approve_scope=lambda _: True, directory=tmp_path
        )

    _approved_case(tmp_path)
    with pytest.raises(ScopeError, match="not approved"):
        create_case_scope(
            CASE_ID, {"VM_1": VM_ID}, approve_scope=lambda _: False, directory=tmp_path
        )
    with pytest.raises(ScopeError, match="approval is required"):
        create_case_scope(CASE_ID, {"VM_1": VM_ID}, approve_scope=None, directory=tmp_path)
    assert not (tmp_path / f"{CASE_ID}.scope.json").exists()


def test_scope_rejects_bad_alias_duplicate_target_and_rebinding(tmp_path: Path) -> None:
    _approved_case(tmp_path)
    with pytest.raises(ScopeError, match="alias is invalid"):
        create_case_scope(
            CASE_ID, {"vm-1": VM_ID}, approve_scope=lambda _: True, directory=tmp_path
        )
    with pytest.raises(ScopeError, match="resource IDs must be unique"):
        create_case_scope(
            CASE_ID,
            {"VM_1": VM_ID, "VM_2": VM_ID},
            approve_scope=lambda _: True,
            directory=tmp_path,
        )

    create_case_scope(CASE_ID, {"VM_1": VM_ID}, approve_scope=lambda _: True, directory=tmp_path)
    with pytest.raises(ScopeError, match="already exists"):
        create_case_scope(
            CASE_ID, {"VM_1": VM_ID}, approve_scope=lambda _: True, directory=tmp_path
        )


def test_scope_duration_is_bounded(tmp_path: Path) -> None:
    _approved_case(tmp_path)
    with pytest.raises(ScopeError, match="duration"):
        create_case_scope(
            CASE_ID,
            {"VM_1": VM_ID},
            approve_scope=lambda _: True,
            expires_in_minutes=1_441,
            directory=tmp_path,
        )
    with pytest.raises(ScopeError, match="duration"):
        create_case_scope(
            CASE_ID,
            {"VM_1": VM_ID},
            approve_scope=lambda _: True,
            expires_in_minutes=True,
            directory=tmp_path,
        )


def test_broker_revalidates_and_local_operator_approves_each_query(tmp_path: Path) -> None:
    _scope(tmp_path)
    seen = []
    authorized = authorize_query(
        CASE_ID,
        _proposal(),
        approve_query=lambda review: seen.append(review) is None,
        directory=tmp_path,
    )

    assert authorized is not None
    assert authorized.resource_id == VM_ID
    assert authorized.operation == "vm_cpu"
    assert authorized.time_range_minutes == 30
    assert len(seen) == 1
    assert seen[0].resource_id == VM_ID
    assert "demo-vm" not in repr(authorized)


def test_rejected_plan_and_operator_denial_return_no_capability(tmp_path: Path) -> None:
    _scope(tmp_path)
    called = []
    rejected = authorize_query(
        CASE_ID,
        _proposal("reject", "NONE", 1),
        approve_query=lambda review: called.append(review) is None,
        directory=tmp_path,
    )
    denied = authorize_query(
        CASE_ID, _proposal(), approve_query=lambda _: False, directory=tmp_path
    )
    assert rejected is None
    assert denied is None
    assert called == []


@pytest.mark.parametrize(
    ("proposal", "message"),
    [
        (_proposal("vm_cpu", "VM_99"), "invalid for the approved case scope"),
        (_proposal("sql_metrics", "VM_1"), "invalid for the approved case scope"),
    ],
)
def test_broker_rejects_out_of_scope_alias_and_operation(
    tmp_path: Path, proposal: QueryProposal, message: str
) -> None:
    _scope(tmp_path)
    with pytest.raises(BrokerError, match=message):
        authorize_query(CASE_ID, proposal, approve_query=lambda _: True, directory=tmp_path)


def test_broker_requires_query_approval_and_fails_if_approval_callback_throws(
    tmp_path: Path,
) -> None:
    _scope(tmp_path)
    with pytest.raises(BrokerError, match="approval is required"):
        authorize_query(CASE_ID, _proposal(), approve_query=None, directory=tmp_path)

    def fail(_review: object) -> bool:
        raise RuntimeError("UI disconnected")

    with pytest.raises(BrokerError, match="no Azure query was authorized"):
        authorize_query(CASE_ID, _proposal(), approve_query=fail, directory=tmp_path)


def test_broker_rechecks_case_approval_and_scope_expiry(tmp_path: Path) -> None:
    _scope(tmp_path)
    case_path = tmp_path / f"{CASE_ID}.json"
    case_data = json.loads(case_path.read_text(encoding="utf-8"))
    case_data["approved"] = False
    case_path.write_text(json.dumps(case_data), encoding="utf-8")
    with pytest.raises(BrokerError, match="scope is unavailable or invalid"):
        authorize_query(CASE_ID, _proposal(), approve_query=lambda _: True, directory=tmp_path)

    case_data["approved"] = True
    case_path.write_text(json.dumps(case_data), encoding="utf-8")
    scope_path = tmp_path / f"{CASE_ID}.scope.json"
    scope_data = json.loads(scope_path.read_text(encoding="utf-8"))
    now = datetime.now(UTC)
    scope_data["created_at"] = (now - timedelta(minutes=2)).isoformat().replace("+00:00", "Z")
    scope_data["expires_at"] = (now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    scope_path.write_text(json.dumps(scope_data), encoding="utf-8")
    with pytest.raises(BrokerError, match="has expired"):
        authorize_query(CASE_ID, _proposal(), approve_query=lambda _: True, directory=tmp_path)


def test_broker_fails_closed_if_private_scope_permissions_are_tampered(tmp_path: Path) -> None:
    _scope(tmp_path)
    scope_path = tmp_path / f"{CASE_ID}.scope.json"
    scope_data = json.loads(scope_path.read_text(encoding="utf-8"))
    scope_data["targets"][0]["operations"] = ["logic_runs"]
    scope_path.write_text(json.dumps(scope_data), encoding="utf-8")
    with pytest.raises(BrokerError, match="scope is unavailable or invalid"):
        case_capabilities(CASE_ID, tmp_path)


def test_execute_query_uses_only_fixed_read_adapters_for_each_supported_operation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _approved_case(tmp_path)
    create_case_scope(
        CASE_ID,
        {"VM_1": VM_ID, "APP_1": APP_ID, "LOGIC_1": LOGIC_ID, "SQL_1": SQL_ID},
        approve_scope=lambda _: True,
        directory=tmp_path,
    )
    monkeypatch.setattr("airlock.azure.shutil.which", lambda name: "C:/Azure/az.cmd")
    calls: list[list[str]] = []
    recent = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
    old = (datetime.now(UTC) - timedelta(hours=2)).isoformat()

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        assert kwargs["shell"] is False
        assert kwargs["capture_output"] is True
        if command[1] == "rest":
            payload = {
                "value": [
                    {
                        "properties": {
                            "startTime": recent,
                            "endTime": recent,
                            "status": "Failed",
                            "code": "InternalServerError",
                            "error": {"code": "Failure", "message": "invented error"},
                            "inputs": {"password": "must never leave local projection"},
                            "outputs": {"token": "must never leave local projection"},
                        },
                    },
                    {"properties": {"startTime": old, "status": "Succeeded"}},
                ]
            }
        else:
            payload = {"value": [{"name": {"value": "demo metric"}, "timeseries": []}]}
        return subprocess.CompletedProcess(command, 0, json.dumps(payload))

    monkeypatch.setattr("airlock.azure.subprocess.run", fake_run)
    proposals = [
        _proposal("vm_cpu", "VM_1", 30),
        _proposal("app_failures", "APP_1", 30),
        _proposal("logic_runs", "LOGIC_1", 30),
        _proposal("sql_metrics", "SQL_1", 30),
    ]
    files_before = {path.name for path in tmp_path.iterdir()}
    outputs = [
        execute_query(CASE_ID, proposal, approve_query=lambda _: True, directory=tmp_path)
        for proposal in proposals
    ]

    assert all(isinstance(output, str) for output in outputs)
    assert {path.name for path in tmp_path.iterdir()} == files_before
    assert json.loads(outputs[0])["target_alias"] == "VM_1"
    assert len(calls) == 5  # SQL uses separate, compatible aggregations for deadlocks.
    metric_calls = [command for command in calls if command[1:4] == ["monitor", "metrics", "list"]]
    assert len(metric_calls) == 4
    expected_metrics = [
        {"Percentage CPU"},
        {"requests/failed", "exceptions/count"},
        {"cpu_percent", "physical_data_read_percent", "log_write_percent"},
        {"deadlock"},
    ]
    for command, expected in zip(metric_calls, expected_metrics, strict=True):
        metric_start = command.index("--metrics") + 1
        metric_end = command.index("--start-time")
        assert set(command[metric_start:metric_end]) == expected
        assert "--resource" in command
        assert "--interval" in command and command[command.index("--interval") + 1] == "1m"
        start = datetime.fromisoformat(command[command.index("--start-time") + 1])
        end = datetime.fromisoformat(command[command.index("--end-time") + 1])
        assert timedelta(minutes=29, seconds=58) <= end - start <= timedelta(minutes=30, seconds=2)
    assert all("delete" not in command and "update" not in command for command in calls)

    logic_command = next(command for command in calls if command[1] == "rest")
    assert logic_command[logic_command.index("--method") + 1] == "get"
    assert (
        logic_command[logic_command.index("--url") + 1] == f"{LOGIC_ID}/runs?api-version=2019-05-01"
    )
    logic_output = json.loads(outputs[2])
    parameters = logic_command[logic_command.index("--url-parameters") + 1 :]
    assert parameters[:2] == [
        "$top=100",
        f"$filter=StartTime ge '{logic_output['window']['start']}'",
    ]
    runs = logic_output["result"]["runs"]
    assert len(runs) == 1
    assert runs[0]["status"] == "Failed"
    assert "inputs" not in outputs[2] and "outputs" not in outputs[2]


def test_denied_query_does_not_resolve_or_invoke_azure_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _scope(tmp_path)

    def fail_which(_name: str) -> None:
        raise AssertionError("Azure CLI must not be resolved after a denied query")

    monkeypatch.setattr("airlock.azure.shutil.which", fail_which)
    assert (
        execute_query(CASE_ID, _proposal(), approve_query=lambda _: False, directory=tmp_path)
        is None
    )


def test_azure_failure_does_not_echo_raw_cli_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _scope(tmp_path)
    monkeypatch.setattr("airlock.azure.shutil.which", lambda name: "C:/Azure/az.cmd")

    def fail_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.CalledProcessError(
            1, command, output="invented-secret", stderr="invented-secret"
        )

    monkeypatch.setattr("airlock.azure.subprocess.run", fail_run)
    with pytest.raises(BrokerError, match="Azure read failed; no result was released") as error:
        execute_query(CASE_ID, _proposal(), approve_query=lambda _: True, directory=tmp_path)
    assert "invented-secret" not in str(error.value)


def test_azure_response_over_limit_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _scope(tmp_path)
    monkeypatch.setattr("airlock.azure.shutil.which", lambda name: "C:/Azure/az.cmd")

    def oversized_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, json.dumps({"data": "x" * 1_100_000}))

    monkeypatch.setattr("airlock.azure.subprocess.run", oversized_run)
    with pytest.raises(BrokerError, match="Azure read failed; no result was released"):
        execute_query(CASE_ID, _proposal(), approve_query=lambda _: True, directory=tmp_path)
