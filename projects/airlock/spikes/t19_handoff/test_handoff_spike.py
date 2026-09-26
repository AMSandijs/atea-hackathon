"""Offline T19 spike checks. Run explicitly: pytest spikes/t19_handoff (never calls Azure)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import handoff_spike as hs

from airlock.planner import QueryProposal

CASE = "a" * 24
OTHER_CASE = "b" * 24
T0 = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)


def _proposal(alias: str = "VM_1") -> QueryProposal:
    return QueryProposal(operation="vm_cpu", target_alias=alias, time_range_minutes=30)


def _record_path(root: Path, case_id: str, request_id: str) -> Path:
    return root / f"{case_id}.req-{request_id}.json"


def test_spike_does_not_load_azure_or_broker() -> None:
    assert "airlock.azure" not in sys.modules
    assert "airlock.broker" not in sys.modules


def test_enqueue_claim_release_round_trip_and_record_has_no_goal_or_real_ids(
    tmp_path: Path,
) -> None:
    status, request_id = hs.enqueue(tmp_path, CASE, _proposal(), now=T0)
    assert status == "queued"
    raw = _record_path(tmp_path, CASE, request_id).read_text(encoding="utf-8")
    assert "/subscriptions/" not in raw and "goal" not in raw
    assert set(json.loads(raw)) == hs._KEYS
    assert hs.status(tmp_path, CASE, request_id, now=T0) == {"status": "queued"}

    gui = hs.Supervisor(tmp_path, started_at=T0 - timedelta(seconds=1))
    record = gui.claim_next(now=T0)
    assert record is not None and record.request_id == request_id
    for state in ("awaiting_query_approval", "running", "awaiting_result_review"):
        gui.transition(request_id, state)
        assert hs.status(tmp_path, CASE, request_id, now=T0) == {"status": state}
    gui.transition(request_id, "released", evidence_id="c" * 24)
    assert hs.status(tmp_path, CASE, request_id, now=T0) == {
        "status": "released",
        "evidence_id": "c" * 24,
    }
    # Repeated polling never changes state or reruns anything.
    assert hs.status(tmp_path, CASE, request_id, now=T0 + timedelta(days=1))["status"] == "released"


def test_terminal_states_are_immutable_and_skipping_approval_is_illegal(tmp_path: Path) -> None:
    _, request_id = hs.enqueue(tmp_path, CASE, _proposal(), now=T0)
    gui = hs.Supervisor(tmp_path, started_at=T0)
    gui.claim_next(now=T0)
    with pytest.raises(hs.HandoffError):
        gui.transition(request_id, "running")  # cannot skip query approval
    with pytest.raises(hs.HandoffError):
        gui.transition(request_id, "released", evidence_id="c" * 24)
    gui.transition(request_id, "awaiting_query_approval")
    gui.transition(request_id, "denied")
    for state in ("running", "released", "awaiting_query_approval", "cancelled"):
        with pytest.raises(hs.HandoffError):
            gui.transition(request_id, state, evidence_id="c" * 24 if state == "released" else None)


@pytest.mark.parametrize(
    "case_id, request_id",
    [
        ("A" * 24, "c" * 24),
        ("../" + "a" * 21, "c" * 24),
        (CASE, "c" * 23),
        (CASE, "c" * 24 + "\\x"),
        (CASE, None),
        (123, "c" * 24),
    ],
)
def test_malformed_ids_are_unknown(tmp_path: Path, case_id: object, request_id: object) -> None:
    assert hs.status(tmp_path, case_id, request_id) == {"status": "unknown"}  # type: ignore[arg-type]


def test_cross_case_status_and_rebinding_are_unknown_and_never_claimed(tmp_path: Path) -> None:
    _, request_id = hs.enqueue(tmp_path, CASE, _proposal(), now=T0)
    assert hs.status(tmp_path, OTHER_CASE, request_id, now=T0) == {"status": "unknown"}

    # A record copied under another case's name stays bound to its original case.
    original = _record_path(tmp_path, CASE, request_id).read_bytes()
    _record_path(tmp_path, OTHER_CASE, request_id).write_bytes(original)
    _record_path(tmp_path, CASE, request_id).unlink()
    assert hs.status(tmp_path, OTHER_CASE, request_id, now=T0) == {"status": "unknown"}
    assert hs.Supervisor(tmp_path, started_at=T0).claim_next(now=T0) is None


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(extra="x"),
        lambda d: d.pop("deadline_at"),
        lambda d: d.update(status="approved"),
        lambda d: d.update(version=2),
        lambda d: d["proposal"].update(target_alias="/subscriptions/x"),
        lambda d: d["proposal"].update(operation="az vm delete"),
        lambda d: d["proposal"].update(time_range_minutes=99_999),
        lambda d: d["proposal"].update(kql="Heartbeat"),
        lambda d: d.update(
            proposal={"operation": "reject", "target_alias": "NONE", "time_range_minutes": 1}
        ),
        lambda d: d.update(evidence_id="c" * 24),
        lambda d: d.update(created_at="2026-09-26T12:00:00"),
        lambda d: d.update(claim_by=d["created_at"]),
    ],
)
def test_malformed_records_are_unknown_and_never_claimed(tmp_path: Path, mutate) -> None:
    _, request_id = hs.enqueue(tmp_path, CASE, _proposal(), now=T0)
    path = _record_path(tmp_path, CASE, request_id)
    data = json.loads(path.read_text(encoding="utf-8"))
    mutate(data)
    path.write_text(json.dumps(data), encoding="utf-8")
    assert hs.status(tmp_path, CASE, request_id, now=T0) == {"status": "unknown"}
    assert hs.Supervisor(tmp_path, started_at=T0).claim_next(now=T0) is None


def test_oversized_and_non_json_records_are_unknown(tmp_path: Path) -> None:
    for index, payload in enumerate((b"{" + b" " * hs.MAX_RECORD_BYTES + b"}", b"\xff\xfe", b"[]")):
        request_id = f"{index:024x}"
        _record_path(tmp_path, CASE, request_id).write_bytes(payload)
        assert hs.status(tmp_path, CASE, request_id, now=T0) == {"status": "unknown"}
    assert hs.Supervisor(tmp_path, started_at=T0).claim_next(now=T0) is None


def test_unclaimed_request_expires_and_is_never_claimed(tmp_path: Path) -> None:
    _, request_id = hs.enqueue(tmp_path, CASE, _proposal(), now=T0, claim_seconds=60)
    later = T0 + timedelta(seconds=60)
    assert hs.status(tmp_path, CASE, request_id, now=later) == {"status": "expired"}
    assert hs.Supervisor(tmp_path, started_at=T0).claim_next(now=later) is None


def test_claimed_request_past_deadline_reads_expired_after_gui_crash(tmp_path: Path) -> None:
    _, request_id = hs.enqueue(tmp_path, CASE, _proposal(), now=T0, deadline_minutes=30)
    gui = hs.Supervisor(tmp_path, started_at=T0)
    gui.claim_next(now=T0)
    gui.transition(request_id, "awaiting_query_approval")
    del gui  # crash: nothing is resolved by the owner
    assert hs.status(tmp_path, CASE, request_id, now=T0 + timedelta(minutes=30)) == {
        "status": "expired"
    }


def test_requests_older_than_the_supervisor_are_not_replayed_after_restart(tmp_path: Path) -> None:
    _, request_id = hs.enqueue(tmp_path, CASE, _proposal(), now=T0)
    restarted = hs.Supervisor(tmp_path, started_at=T0 + timedelta(seconds=5))
    assert restarted.claim_next(now=T0 + timedelta(seconds=6)) is None
    assert hs.status(tmp_path, CASE, request_id, now=T0 + timedelta(seconds=6)) == {
        "status": "queued"
    }


def test_claim_is_single_use_even_if_record_is_reset_to_queued(tmp_path: Path) -> None:
    _, request_id = hs.enqueue(tmp_path, CASE, _proposal(), now=T0)
    path = _record_path(tmp_path, CASE, request_id)
    queued_bytes = path.read_bytes()
    first = hs.Supervisor(tmp_path, started_at=T0)
    assert first.claim_next(now=T0) is not None
    first.transition(request_id, "awaiting_query_approval")
    first.transition(request_id, "denied")

    path.write_bytes(queued_bytes)  # replay the original queued record
    assert first.claim_next(now=T0) is None  # consumed in memory
    second = hs.Supervisor(tmp_path, started_at=T0)
    assert second.claim_next(now=T0) is None  # persistent claim marker


def test_duplicate_requests_for_one_case_mcp_busy_and_gui_rejects_extra(tmp_path: Path) -> None:
    _, first_id = hs.enqueue(tmp_path, CASE, _proposal(), now=T0)
    assert hs.enqueue(tmp_path, CASE, _proposal(), now=T0) == ("busy", first_id)

    # Two MCP processes racing past the best-effort check: GUI claim is authoritative.
    racing_id = "f" * 24
    record = hs.Record(
        CASE,
        racing_id,
        "queued",
        _proposal(),
        T0 + timedelta(seconds=1),
        T0 + timedelta(minutes=5),
        T0 + timedelta(minutes=30),
        None,
    )
    hs._write_new(_record_path(tmp_path, CASE, racing_id), hs._payload(record))
    gui = hs.Supervisor(tmp_path, started_at=T0)
    claimed = gui.claim_next(now=T0 + timedelta(seconds=2))
    assert claimed is not None and claimed.request_id == first_id
    assert hs.status(tmp_path, CASE, racing_id, now=T0)["status"] == "rejected"
    assert gui.claim_next(now=T0 + timedelta(seconds=2)) is None  # one in flight


def test_other_case_waits_until_current_request_is_terminal(tmp_path: Path) -> None:
    _, first = hs.enqueue(tmp_path, CASE, _proposal(), now=T0)
    _, second = hs.enqueue(tmp_path, OTHER_CASE, _proposal(), now=T0 + timedelta(seconds=1))
    gui = hs.Supervisor(tmp_path, started_at=T0)
    assert gui.claim_next(now=T0 + timedelta(seconds=2)).request_id == first
    assert gui.claim_next(now=T0 + timedelta(seconds=2)) is None
    gui.transition(first, "cancelled")
    assert gui.claim_next(now=T0 + timedelta(seconds=2)).request_id == second


def test_enqueue_never_overwrites_existing_record(tmp_path: Path) -> None:
    path = _record_path(tmp_path, CASE, "c" * 24)
    path.write_bytes(b"sentinel")
    with pytest.raises(FileExistsError):
        hs._write_new(path, b"replacement")
    assert path.read_bytes() == b"sentinel"
    assert not list(tmp_path.glob(".*.tmp"))


def test_shutdown_cancels_in_flight_request_never_approves(tmp_path: Path) -> None:
    _, request_id = hs.enqueue(tmp_path, CASE, _proposal(), now=T0)
    gui = hs.Supervisor(tmp_path, started_at=T0)
    gui.claim_next(now=T0)
    gui.transition(request_id, "awaiting_query_approval")
    gui.shutdown()
    assert hs.status(tmp_path, CASE, request_id, now=T0) == {"status": "cancelled"}


def test_rejected_proposal_is_never_queued(tmp_path: Path) -> None:
    reject = QueryProposal(operation="reject", target_alias="NONE", time_range_minutes=1)
    with pytest.raises(hs.HandoffError):
        hs.enqueue(tmp_path, CASE, reject, now=T0)
    assert not list(tmp_path.iterdir())


_CLAIM_SCRIPT = """
import sys, time
from datetime import datetime, UTC
sys.path.insert(0, sys.argv[1])
import handoff_spike as hs
from pathlib import Path
start = float(sys.argv[3])
while time.time() < start:
    pass
gui = hs.Supervisor(Path(sys.argv[2]), started_at=datetime(2000, 1, 1, tzinfo=UTC))
record = gui.claim_next()
print(record.request_id if record else "none")
"""


def test_concurrent_supervisor_processes_claim_exactly_once(tmp_path: Path) -> None:
    _, request_id = hs.enqueue(tmp_path, CASE, _proposal())
    start = str(time.time() + 1.5)
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2])}
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", _CLAIM_SCRIPT, str(Path(__file__).parent), str(tmp_path), start],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        for _ in range(6)
    ]
    outputs = [proc.communicate(timeout=60) for proc in procs]
    results = [out.strip() for out, _ in outputs]
    assert all(proc.returncode == 0 for proc in procs), [err for _, err in outputs]
    assert results.count(request_id) == 1, results
    assert results.count("none") == 5, results


@pytest.mark.skipif(os.name != "nt", reason="Windows sharing-violation behaviour")
def test_owner_replace_waits_out_an_open_reader_handle(tmp_path: Path) -> None:
    _, request_id = hs.enqueue(tmp_path, CASE, _proposal())
    gui = hs.Supervisor(tmp_path, started_at=datetime(2000, 1, 1, tzinfo=UTC))
    gui.claim_next()
    path = _record_path(tmp_path, CASE, request_id)
    handle = path.open("rb")  # emulate an MCP status read in progress
    probe = path.with_name("probe")
    probe.write_bytes(b"x")
    with pytest.raises(PermissionError):  # confirms the platform sharing violation exists
        os.replace(probe, path)
    probe.unlink()
    timer = threading.Timer(0.05, handle.close)
    timer.start()
    gui.transition(request_id, "awaiting_query_approval")
    timer.join()
    assert hs.status(tmp_path, CASE, request_id) == {"status": "awaiting_query_approval"}


def test_status_polling_during_owner_writes_never_sees_partial_or_foreign_state(
    tmp_path: Path,
) -> None:
    _, request_id = hs.enqueue(tmp_path, CASE, _proposal())
    gui = hs.Supervisor(tmp_path, started_at=datetime(2000, 1, 1, tzinfo=UTC))
    gui.claim_next()
    seen: list[str] = []
    stop = threading.Event()

    def poll() -> None:
        while not stop.is_set():
            seen.append(hs.status(tmp_path, CASE, request_id)["status"])

    poller = threading.Thread(target=poll)
    poller.start()
    path = _record_path(tmp_path, CASE, request_id)
    for state in ("awaiting_query_approval", "running", "awaiting_result_review"):
        for _ in range(20):  # extra same-state rewrites to maximise reader/writer overlap
            hs._replace(path, hs._payload(gui._owned[request_id]))
        gui.transition(request_id, state)
    gui.transition(request_id, "released", evidence_id="c" * 24)
    stop.set()
    poller.join()
    allowed = {
        "claimed",
        "awaiting_query_approval",
        "running",
        "awaiting_result_review",
        "released",
        "unavailable",
    }
    assert set(seen) <= allowed, set(seen)
    assert "unknown" not in seen


def test_local_root_rejects_unc_and_onedrive(tmp_path: Path) -> None:
    with pytest.raises(hs.HandoffError):
        hs.check_local_root(Path(r"\\server\share\airlock"), env={})
    synced = tmp_path / "OneDrive - Contoso"
    with pytest.raises(hs.HandoffError):
        hs.check_local_root(synced / ".airlock" / "cases", env={"OneDriveCommercial": str(synced)})
    hs.check_local_root(tmp_path / ".airlock" / "cases", env={"OneDrive": str(synced)})
