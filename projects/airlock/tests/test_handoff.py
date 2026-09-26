"""Local MCP-to-GUI request queue: atomic, single-use, fail-closed, no customer data."""

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

from airlock import handoff
from airlock.handoff import HandoffError, RequestSupervisor, enqueue_request, request_status
from airlock.planner import QueryProposal

CASE = "a" * 24
OTHER_CASE = "b" * 24
EVIDENCE = "c" * 24
T0 = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)
EARLY = datetime(2000, 1, 1, tzinfo=UTC)


def _proposal(alias: str = "VM_1") -> QueryProposal:
    return QueryProposal(operation="vm_cpu", target_alias=alias, time_range_minutes=30)


def _enqueue(root: Path, case_id: str = CASE, now: datetime = T0, **kwargs: int) -> str:
    kwargs.setdefault("claim_seconds", 300)
    kwargs.setdefault("deadline_minutes", 30)
    status, request_id = enqueue_request(case_id, _proposal(), directory=root, now=now, **kwargs)
    assert status == "queued"
    return request_id


def _record(root: Path, case_id: str, request_id: str) -> Path:
    return root / "requests" / f"{case_id}.req-{request_id}.json"


def test_round_trip_record_holds_no_goal_or_real_identifiers(tmp_path: Path) -> None:
    request_id = _enqueue(tmp_path)
    raw = _record(tmp_path, CASE, request_id).read_text(encoding="utf-8")
    assert "/subscriptions/" not in raw and "goal" not in raw
    assert set(json.loads(raw)) == {
        "version",
        "case_id",
        "request_id",
        "status",
        "proposal",
        "created_at",
        "claim_by",
        "deadline_at",
        "evidence_id",
    }
    assert request_status(CASE, request_id, tmp_path, now=T0) == {"status": "queued"}

    gui = RequestSupervisor(tmp_path, started_at=T0 - timedelta(seconds=1))
    record = gui.claim_next(CASE, now=T0)
    assert record is not None and record.request_id == request_id
    assert record.proposal == _proposal()
    for state in ("awaiting_query_approval", "running", "awaiting_result_review"):
        gui.transition(request_id, state)
        assert request_status(CASE, request_id, tmp_path, now=T0) == {"status": state}
    gui.transition(request_id, "released", evidence_id=EVIDENCE)
    assert request_status(CASE, request_id, tmp_path, now=T0) == {
        "status": "released",
        "evidence_id": EVIDENCE,
    }
    later = T0 + timedelta(days=1)
    assert request_status(CASE, request_id, tmp_path, now=later)["status"] == "released"


def test_claim_by_is_capped_at_deadline(tmp_path: Path) -> None:
    request_id = _enqueue(tmp_path, claim_seconds=900, deadline_minutes=5)
    data = json.loads(_record(tmp_path, CASE, request_id).read_text(encoding="utf-8"))
    assert data["claim_by"] == data["deadline_at"]


def test_terminal_states_are_immutable_and_approval_cannot_be_skipped(tmp_path: Path) -> None:
    request_id = _enqueue(tmp_path)
    gui = RequestSupervisor(tmp_path, started_at=T0)
    gui.claim_next(CASE, now=T0)
    with pytest.raises(HandoffError):
        gui.transition(request_id, "running")
    with pytest.raises(HandoffError):
        gui.transition(request_id, "released", evidence_id=EVIDENCE)
    gui.transition(request_id, "awaiting_query_approval")
    gui.transition(request_id, "denied")
    for state in ("running", "awaiting_query_approval", "cancelled", "released"):
        with pytest.raises(HandoffError):
            gui.transition(request_id, state, evidence_id=EVIDENCE if state == "released" else None)


def test_transition_requires_ownership(tmp_path: Path) -> None:
    request_id = _enqueue(tmp_path)
    with pytest.raises(HandoffError):
        RequestSupervisor(tmp_path, started_at=T0).transition(request_id, "cancelled")
    assert request_status(CASE, request_id, tmp_path, now=T0) == {"status": "queued"}


@pytest.mark.parametrize(
    ("case_id", "request_id"),
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
    assert request_status(case_id, request_id, tmp_path) == {"status": "unknown"}  # type: ignore[arg-type]


def test_cross_case_and_rebound_records_are_unknown_and_never_claimed(tmp_path: Path) -> None:
    request_id = _enqueue(tmp_path)
    assert request_status(OTHER_CASE, request_id, tmp_path, now=T0) == {"status": "unknown"}
    original = _record(tmp_path, CASE, request_id)
    _record(tmp_path, OTHER_CASE, request_id).write_bytes(original.read_bytes())
    original.unlink()
    assert request_status(OTHER_CASE, request_id, tmp_path, now=T0) == {"status": "unknown"}
    assert RequestSupervisor(tmp_path, started_at=T0).claim_next(OTHER_CASE, now=T0) is None


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
        lambda d: d.update(evidence_id=EVIDENCE),
        lambda d: d.update(created_at="2026-09-26T12:00:00"),
        lambda d: d.update(claim_by=d["created_at"]),
        lambda d: d.update(version=True),
    ],
)
def test_malformed_records_are_unknown_and_never_claimed(tmp_path: Path, mutate) -> None:
    request_id = _enqueue(tmp_path)
    path = _record(tmp_path, CASE, request_id)
    data = json.loads(path.read_text(encoding="utf-8"))
    mutate(data)
    path.write_text(json.dumps(data), encoding="utf-8")
    assert request_status(CASE, request_id, tmp_path, now=T0) == {"status": "unknown"}
    assert RequestSupervisor(tmp_path, started_at=T0).claim_next(CASE, now=T0) is None


def test_oversized_and_non_json_records_are_unknown(tmp_path: Path) -> None:
    (tmp_path / "requests").mkdir()
    payloads = (b"{" + b" " * 5_000 + b"}", b"\xff\xfe", b"[]")
    for index, payload in enumerate(payloads):
        request_id = f"{index:024x}"
        _record(tmp_path, CASE, request_id).write_bytes(payload)
        assert request_status(CASE, request_id, tmp_path, now=T0) == {"status": "unknown"}
    assert RequestSupervisor(tmp_path, started_at=T0).claim_next(CASE, now=T0) is None


def test_unclaimed_request_expires_and_is_never_claimed(tmp_path: Path) -> None:
    request_id = _enqueue(tmp_path, claim_seconds=60)
    later = T0 + timedelta(seconds=60)
    assert request_status(CASE, request_id, tmp_path, now=later) == {"status": "expired"}
    assert RequestSupervisor(tmp_path, started_at=T0).claim_next(CASE, now=later) is None


def test_in_flight_request_reads_expired_after_deadline_when_gui_crashed(tmp_path: Path) -> None:
    request_id = _enqueue(tmp_path, deadline_minutes=30)
    gui = RequestSupervisor(tmp_path, started_at=T0)
    gui.claim_next(CASE, now=T0)
    gui.transition(request_id, "awaiting_query_approval")
    del gui
    later = T0 + timedelta(minutes=30)
    assert request_status(CASE, request_id, tmp_path, now=later) == {"status": "expired"}


def test_requests_older_than_the_supervisor_are_never_replayed(tmp_path: Path) -> None:
    request_id = _enqueue(tmp_path)
    restarted = RequestSupervisor(tmp_path, started_at=T0 + timedelta(seconds=5))
    assert restarted.claim_next(CASE, now=T0 + timedelta(seconds=6)) is None
    assert request_status(CASE, request_id, tmp_path, now=T0) == {"status": "queued"}


def test_claim_is_single_use_even_if_record_is_reset_to_queued(tmp_path: Path) -> None:
    request_id = _enqueue(tmp_path)
    path = _record(tmp_path, CASE, request_id)
    queued_bytes = path.read_bytes()
    first = RequestSupervisor(tmp_path, started_at=T0)
    assert first.claim_next(CASE, now=T0) is not None
    first.transition(request_id, "awaiting_query_approval")
    first.transition(request_id, "denied")
    path.write_bytes(queued_bytes)
    assert first.claim_next(CASE, now=T0) is None
    assert RequestSupervisor(tmp_path, started_at=T0).claim_next(CASE, now=T0) is None


def test_duplicate_for_case_is_busy_and_raced_duplicate_is_rejected(tmp_path: Path) -> None:
    first_id = _enqueue(tmp_path)
    assert enqueue_request(
        CASE,
        _proposal(),
        claim_seconds=300,
        deadline_minutes=30,
        directory=tmp_path,
        now=T0,
    ) == ("busy", first_id)

    racing_id = "f" * 24
    record = handoff.HandoffRecord(
        CASE,
        racing_id,
        "queued",
        _proposal(),
        T0 + timedelta(seconds=1),
        T0 + timedelta(minutes=5),
        T0 + timedelta(minutes=30),
        None,
    )
    handoff._write_new(_record(tmp_path, CASE, racing_id), handoff._payload(record))
    gui = RequestSupervisor(tmp_path, started_at=T0)
    claimed = gui.claim_next(CASE, now=T0 + timedelta(seconds=2))
    assert claimed is not None and claimed.request_id == first_id
    assert request_status(CASE, racing_id, tmp_path, now=T0)["status"] == "rejected"
    assert gui.claim_next(CASE, now=T0 + timedelta(seconds=2)) is None


def test_supervisor_claims_only_the_loaded_case_and_one_at_a_time(tmp_path: Path) -> None:
    first = _enqueue(tmp_path)
    other = _enqueue(tmp_path, OTHER_CASE, now=T0 + timedelta(seconds=1))
    gui = RequestSupervisor(tmp_path, started_at=T0)
    assert gui.claim_next(OTHER_CASE, now=T0 + timedelta(seconds=2)).request_id == other
    assert gui.claim_next(CASE, now=T0 + timedelta(seconds=2)) is None
    gui.transition(other, "cancelled")
    assert gui.claim_next(CASE, now=T0 + timedelta(seconds=2)).request_id == first


def test_enqueue_never_overwrites_existing_record(tmp_path: Path) -> None:
    (tmp_path / "requests").mkdir()
    path = _record(tmp_path, CASE, "c" * 24)
    path.write_bytes(b"sentinel")
    with pytest.raises(FileExistsError):
        handoff._write_new(path, b"replacement")
    assert path.read_bytes() == b"sentinel"
    assert not list((tmp_path / "requests").glob(".*.tmp"))


def test_rejected_proposal_is_never_queued(tmp_path: Path) -> None:
    reject = QueryProposal(operation="reject", target_alias="NONE", time_range_minutes=1)
    with pytest.raises(HandoffError):
        enqueue_request(
            CASE, reject, claim_seconds=300, deadline_minutes=30, directory=tmp_path, now=T0
        )
    assert not list((tmp_path / "requests").glob("*.json"))


def test_shutdown_cancels_in_flight_request(tmp_path: Path) -> None:
    request_id = _enqueue(tmp_path)
    gui = RequestSupervisor(tmp_path, started_at=T0)
    gui.claim_next(CASE, now=T0)
    gui.transition(request_id, "awaiting_query_approval")
    gui.shutdown()
    assert request_status(CASE, request_id, tmp_path, now=T0) == {"status": "cancelled"}
    with pytest.raises(HandoffError):
        gui.transition(request_id, "running")


def test_cleanup_removes_only_stale_records_markers_and_temp_files(tmp_path: Path) -> None:
    stale = _enqueue(tmp_path)
    gui = RequestSupervisor(tmp_path, started_at=T0)
    gui.claim_next(CASE, now=T0)
    gui.transition(stale, "cancelled")
    fresh = _enqueue(tmp_path, OTHER_CASE, now=T0 + timedelta(days=1))
    queue = tmp_path / "requests"
    old_tmp = queue / ".leftover.tmp"
    old_tmp.write_bytes(b"x")
    garbage = queue / f"{CASE}.req-{'d' * 24}.json"
    garbage.write_bytes(b"not json")
    old = time.time() - 2 * 24 * 3600
    os.utime(old_tmp, (old, old))
    os.utime(garbage, (old, old))

    removed = handoff.cleanup_requests(tmp_path, now=T0 + timedelta(days=1, minutes=31))

    assert removed == 4  # stale record, its claim marker, temp file, old invalid record
    assert not _record(tmp_path, CASE, stale).exists()
    assert not (queue / f"{CASE}.req-{stale}.claim").exists()
    assert _record(tmp_path, OTHER_CASE, fresh).exists()
    assert not old_tmp.exists() and not garbage.exists()


def test_queue_directory_rejects_unc_and_synced_folders(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(HandoffError):
        handoff.queue_directory(Path(r"\\server\share\airlock"))
    synced = tmp_path / "OneDrive - Contoso"
    monkeypatch.setenv("OneDriveCommercial", str(synced))
    with pytest.raises(HandoffError):
        handoff.queue_directory(synced / ".airlock" / "cases")
    assert not (synced / ".airlock").exists()
    assert handoff.queue_directory(tmp_path / "cases") == tmp_path / "cases" / "requests"
    assert (tmp_path / "cases" / "requests").is_dir()


_CLAIM_SCRIPT = """
import sys, time
from datetime import datetime, UTC
from pathlib import Path
from airlock.handoff import RequestSupervisor
start = float(sys.argv[2])
while time.time() < start:
    pass
gui = RequestSupervisor(Path(sys.argv[1]), started_at=datetime(2000, 1, 1, tzinfo=UTC))
record = gui.claim_next(sys.argv[3])
print(record.request_id if record else "none")
"""


def test_concurrent_supervisor_processes_claim_exactly_once(tmp_path: Path) -> None:
    request_id = _enqueue(tmp_path, now=datetime.now(UTC))
    start = str(time.time() + 1.5)
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", _CLAIM_SCRIPT, str(tmp_path), start, CASE],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=Path(__file__).parents[1],
        )
        for _ in range(6)
    ]
    outputs = [proc.communicate(timeout=60) for proc in procs]
    results = [out.strip() for out, _ in outputs]
    assert all(proc.returncode == 0 for proc in procs), [err for _, err in outputs]
    assert results.count(request_id) == 1, results
    assert results.count("none") == 5, results


@pytest.mark.skipif(os.name != "nt", reason="Windows sharing-violation behaviour")
def test_owner_update_waits_out_an_open_reader_handle(tmp_path: Path) -> None:
    request_id = _enqueue(tmp_path, now=datetime.now(UTC))
    gui = RequestSupervisor(tmp_path, started_at=EARLY)
    gui.claim_next(CASE)
    path = _record(tmp_path, CASE, request_id)
    handle = path.open("rb")
    timer = threading.Timer(0.05, handle.close)
    timer.start()
    gui.transition(request_id, "awaiting_query_approval")
    timer.join()
    assert request_status(CASE, request_id, tmp_path) == {"status": "awaiting_query_approval"}


def test_persistent_sharing_violation_reads_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request_id = _enqueue(tmp_path)

    def locked(*_args: object, **_kwargs: object) -> object:
        raise PermissionError("sharing violation")

    monkeypatch.setattr(Path, "open", locked)
    monkeypatch.setattr(handoff.time, "sleep", lambda _: None)
    assert request_status(CASE, request_id, tmp_path, now=T0) == {"status": "unavailable"}


def test_status_polling_during_owner_writes_never_sees_invalid_state(tmp_path: Path) -> None:
    request_id = _enqueue(tmp_path, now=datetime.now(UTC))
    gui = RequestSupervisor(tmp_path, started_at=EARLY)
    gui.claim_next(CASE)
    seen: list[str] = []
    stop = threading.Event()

    def poll() -> None:
        while not stop.is_set():
            seen.append(request_status(CASE, request_id, tmp_path)["status"])

    poller = threading.Thread(target=poll)
    poller.start()
    for state in ("awaiting_query_approval", "running", "awaiting_result_review"):
        gui.transition(request_id, state)
    gui.transition(request_id, "released", evidence_id=EVIDENCE)
    stop.set()
    poller.join()
    assert set(seen) <= {
        "claimed",
        "awaiting_query_approval",
        "running",
        "awaiting_result_review",
        "released",
        "unavailable",
    }, set(seen)
