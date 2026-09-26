"""T19 THROWAWAY SPIKE — not production code, not imported by the airlock package.

Proves the file-queue mechanics chosen in ARCHITECTURE.md ("MCP-to-GUI handoff"):
atomic no-overwrite enqueue, exclusive single-use claim, owner-only state writes,
strict record validation, derived expiry, and Windows sharing-violation tolerance.
It never plans with a model, touches scope/resource IDs, or calls Azure.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from airlock.planner import QueryProposal

_ID = re.compile(r"[0-9a-f]{24}\Z")
_RECORD_NAME = re.compile(r"([0-9a-f]{24})\.req-([0-9a-f]{24})\.json\Z")
MAX_RECORD_BYTES = 4_096
_KEYS = {
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
TERMINAL = frozenset(
    {"released", "denied", "rejected", "blocked", "failed", "expired", "cancelled"}
)
ACTIVE = frozenset(
    {"queued", "claimed", "awaiting_query_approval", "running", "awaiting_result_review"}
)
_FAIL = {"failed", "cancelled", "expired"}
TRANSITIONS: dict[str, frozenset[str]] = {
    "claimed": frozenset({"awaiting_query_approval", "rejected"} | _FAIL),
    "awaiting_query_approval": frozenset({"running", "denied", "rejected"} | _FAIL),
    "running": frozenset({"awaiting_result_review", "blocked"} | _FAIL),
    "awaiting_result_review": frozenset({"released", "denied", "blocked"} | _FAIL),
}


class HandoffError(RuntimeError):
    """A queue operation failed closed."""


@dataclass(frozen=True)
class Record:
    case_id: str
    request_id: str
    status: str
    proposal: QueryProposal
    created_at: datetime
    claim_by: datetime
    deadline_at: datetime
    evidence_id: str | None


def check_local_root(root: Path, env: dict[str, str] | None = None) -> None:
    """Refuse network/UNC and OneDrive-synced queue locations."""

    env = dict(os.environ) if env is None else env
    text = str(root)
    if text.startswith(("\\\\", "//")):
        raise HandoffError("queue directory must be on a local fixed drive")
    resolved = os.path.normcase(os.path.abspath(text))
    for name in ("OneDrive", "OneDriveCommercial", "OneDriveConsumer"):
        synced = env.get(name)
        if synced:
            base = os.path.normcase(os.path.abspath(synced))
            if resolved == base or resolved.startswith(base + os.sep):
                raise HandoffError("queue directory must not be in a synced folder")
    if os.name == "nt":
        import ctypes

        drive = os.path.splitdrive(os.path.abspath(text))[0] + "\\"
        if ctypes.windll.kernel32.GetDriveTypeW(drive) != 3:  # DRIVE_FIXED
            raise HandoffError("queue directory must be on a local fixed drive")


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_time(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise HandoffError("invalid timestamp")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise HandoffError("invalid timestamp")
    return parsed.astimezone(UTC)


def _path(root: Path, case_id: str, request_id: str) -> Path:
    if not isinstance(case_id, str) or not isinstance(request_id, str):
        raise HandoffError("invalid ID")
    if not _ID.fullmatch(case_id) or not _ID.fullmatch(request_id):
        raise HandoffError("invalid ID")
    return root / f"{case_id}.req-{request_id}.json"


def _payload(record: Record) -> bytes:
    data = {
        "version": 1,
        "case_id": record.case_id,
        "request_id": record.request_id,
        "status": record.status,
        "proposal": record.proposal.model_dump(),
        "created_at": _iso(record.created_at),
        "claim_by": _iso(record.claim_by),
        "deadline_at": _iso(record.deadline_at),
        "evidence_id": record.evidence_id,
    }
    return json.dumps(data, sort_keys=True).encode("utf-8")


def _parse(raw: bytes, case_id: str, request_id: str) -> Record:
    if len(raw) > MAX_RECORD_BYTES:
        raise HandoffError("record too large")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HandoffError("record is malformed") from exc
    if not isinstance(data, dict) or set(data) != _KEYS or data["version"] != 1:
        raise HandoffError("record is malformed")
    if data["case_id"] != case_id or data["request_id"] != request_id:
        raise HandoffError("record is bound to another case or request")
    status = data["status"]
    if status not in TERMINAL | ACTIVE:
        raise HandoffError("record status is invalid")
    evidence_id = data["evidence_id"]
    if (status == "released") != (evidence_id is not None):
        raise HandoffError("evidence ID is only valid on released records")
    if evidence_id is not None and (
        not isinstance(evidence_id, str) or not _ID.fullmatch(evidence_id)
    ):
        raise HandoffError("evidence ID is invalid")
    try:
        proposal = QueryProposal.model_validate(data["proposal"])
    except Exception as exc:
        raise HandoffError("record proposal is invalid") from exc
    if proposal.operation == "reject":
        raise HandoffError("rejected proposals are never queued")
    created = _parse_time(data["created_at"])
    claim_by = _parse_time(data["claim_by"])
    deadline = _parse_time(data["deadline_at"])
    if not created < claim_by <= deadline:
        raise HandoffError("record timestamps are inconsistent")
    return Record(case_id, request_id, status, proposal, created, claim_by, deadline, evidence_id)


def _read(path: Path, case_id: str, request_id: str, attempts: int = 20) -> Record:
    for attempt in range(attempts):
        try:
            with path.open("rb") as stream:
                raw = stream.read(MAX_RECORD_BYTES + 1)
            return _parse(raw, case_id, request_id)
        except PermissionError:  # Windows sharing violation during an owner replace
            if attempt == attempts - 1:
                raise
            time.sleep(0.005)
    raise AssertionError("unreachable")


def _write_new(path: Path, payload: bytes) -> None:
    """Create ``path`` atomically, never overwriting an existing record."""

    tmp = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
    with tmp.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.link(tmp, path)  # atomic and fails if path exists, on NTFS and POSIX
    finally:
        tmp.unlink(missing_ok=True)


def _replace(path: Path, payload: bytes, attempts: int = 50) -> None:
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
    with tmp.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        for attempt in range(attempts):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:  # a reader holds the file open on Windows
                if attempt == attempts - 1:
                    raise HandoffError("record update failed") from None
                time.sleep(0.005)
    finally:
        tmp.unlink(missing_ok=True)


def effective_status(record: Record, now: datetime) -> str:
    """Expiry is derived by every reader; a stale non-terminal record never looks live."""

    if record.status in TERMINAL:
        return record.status
    if now >= record.deadline_at or (record.status == "queued" and now >= record.claim_by):
        return "expired"
    return record.status


def _active_for_case(root: Path, case_id: str, now: datetime) -> str | None:
    for path in sorted(root.glob(f"{case_id}.req-*.json")):
        match = _RECORD_NAME.fullmatch(path.name)
        if not match:
            continue
        try:
            record = _read(path, match.group(1), match.group(2))
        except (HandoffError, OSError):
            continue
        if effective_status(record, now) in ACTIVE:
            return record.request_id
    return None


def enqueue(
    root: Path,
    case_id: str,
    proposal: QueryProposal,
    *,
    now: datetime | None = None,
    claim_seconds: int = 300,
    deadline_minutes: int = 30,
) -> tuple[str, str]:
    """MCP side: queue one validated typed proposal. Returns (status, request_id)."""

    now = now or datetime.now(UTC)
    if proposal.operation == "reject":
        raise HandoffError("rejected proposals are never queued")
    root.mkdir(parents=True, exist_ok=True)
    active = _active_for_case(root, case_id, now)
    if active is not None:
        return "busy", active  # best-effort; the GUI claim is authoritative
    request_id = secrets.token_hex(12)
    record = Record(
        case_id,
        request_id,
        "queued",
        proposal,
        now,
        now + timedelta(seconds=claim_seconds),
        now + timedelta(minutes=deadline_minutes),
        None,
    )
    _write_new(_path(root, case_id, request_id), _payload(record))
    return "queued", request_id


def status(
    root: Path, case_id: str, request_id: str, now: datetime | None = None
) -> dict[str, str]:
    """MCP side: allow-listed status only; any problem reads as ``unknown``.

    A persistent Windows sharing violation is reported as retryable ``unavailable``.
    """

    try:
        record = _read(_path(root, case_id, request_id), case_id, request_id)
    except PermissionError:
        return {"status": "unavailable"}
    except (HandoffError, OSError):
        return {"status": "unknown"}
    state = effective_status(record, now or datetime.now(UTC))
    if state == "released" and record.evidence_id is not None:
        return {"status": state, "evidence_id": record.evidence_id}
    return {"status": state}


class Supervisor:
    """GUI side: sole claimer/owner. Only claims requests created after it started."""

    def __init__(self, root: Path, started_at: datetime | None = None) -> None:
        self.root = root
        self.started_at = started_at or datetime.now(UTC)
        self._consumed: set[str] = set()
        self._owned: dict[str, Record] = {}

    def _claim(self, record: Record) -> Record | None:
        marker = self.root / f"{record.case_id}.req-{record.request_id}.claim"
        try:
            with marker.open("xb"):
                pass
        except FileExistsError:
            return None  # another supervisor (or an earlier claim) owns it: single use
        self._consumed.add(record.request_id)
        claimed = Record(**{**record.__dict__, "status": "claimed"})
        _replace(_path(self.root, record.case_id, record.request_id), _payload(claimed))
        self._owned[record.request_id] = claimed
        return claimed

    def claim_next(self, now: datetime | None = None) -> Record | None:
        now = now or datetime.now(UTC)
        if any(effective_status(r, now) in ACTIVE for r in self._owned.values()):
            return None  # at most one request in flight
        candidates: list[Record] = []
        for path in self.root.glob("*.req-*.json"):
            match = _RECORD_NAME.fullmatch(path.name)
            if not match or match.group(2) in self._consumed:
                continue
            try:
                record = _read(path, match.group(1), match.group(2))
            except (HandoffError, OSError):
                continue  # malformed/cross-bound: never executed
            if record.status != "queued" or effective_status(record, now) != "queued":
                continue
            if record.created_at < self.started_at:
                continue  # pre-dates this supervisor: left to expire, never replayed
            candidates.append(record)
        candidates.sort(key=lambda r: (r.created_at, r.request_id))
        chosen: Record | None = None
        for record in candidates:
            if chosen is not None and record.case_id == chosen.case_id:
                duplicate = self._claim(record)  # duplicate for same case: reject, no read
                if duplicate is not None:
                    self.transition(duplicate.request_id, "rejected")
                continue
            if chosen is None:
                chosen = self._claim(record)
        return chosen

    def transition(
        self, request_id: str, new_status: str, *, evidence_id: str | None = None
    ) -> Record:
        current = self._owned.get(request_id)
        if current is None:
            raise HandoffError("request is not owned by this supervisor")
        if new_status not in TRANSITIONS.get(current.status, frozenset()):
            raise HandoffError(f"illegal transition {current.status} -> {new_status}")
        if (new_status == "released") != (evidence_id is not None):
            raise HandoffError("evidence ID accompanies release only")
        updated = Record(**{**current.__dict__, "status": new_status, "evidence_id": evidence_id})
        _replace(_path(self.root, current.case_id, request_id), _payload(updated))
        self._owned[request_id] = updated
        return updated

    def shutdown(self) -> None:
        """GUI close: every owned in-flight request becomes cancelled, never approved."""

        for request_id, record in list(self._owned.items()):
            if record.status in ACTIVE:
                self.transition(request_id, "cancelled")
