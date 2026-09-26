"""Local file queue carrying one typed Copilot request from MCP to the GUI supervisor.

Records hold only opaque IDs, an alias-level proposal, status, and timestamps. There is
no listener: the stdio MCP process creates records, and the local GUI claims and owns
them. Every record is untrusted when read; any doubt reads as ``unknown``/``expired``.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import threading
import time
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from .cases import case_directory
from .planner import QueryProposal

_ID = re.compile(r"[0-9a-f]{24}\Z")
_RECORD_NAME = re.compile(r"([0-9a-f]{24})\.req-([0-9a-f]{24})\.json\Z")
_CLAIM_NAME = re.compile(r"[0-9a-f]{24}\.req-[0-9a-f]{24}\.claim\Z")
_MAX_RECORD_BYTES = 4_096
_READ_ATTEMPTS = 20
_REPLACE_ATTEMPTS = 50
_RETRY_SECONDS = 0.005
_RETENTION = timedelta(hours=24)
_TEMP_RETENTION_SECONDS = 3_600
_KEYS = frozenset(
    {
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
)
TERMINAL = frozenset(
    {"released", "denied", "rejected", "blocked", "failed", "expired", "cancelled"}
)
ACTIVE = frozenset(
    {"queued", "claimed", "awaiting_query_approval", "running", "awaiting_result_review"}
)
_ABORT = frozenset({"failed", "cancelled", "expired"})
_TRANSITIONS: dict[str, frozenset[str]] = {
    "claimed": frozenset({"awaiting_query_approval", "rejected"}) | _ABORT,
    "awaiting_query_approval": frozenset({"running", "denied", "rejected"}) | _ABORT,
    "running": frozenset({"awaiting_result_review", "blocked"}) | _ABORT,
    "awaiting_result_review": frozenset({"released", "denied", "blocked"}) | _ABORT,
}


class HandoffError(RuntimeError):
    """A queue operation failed closed."""


@dataclass(frozen=True)
class HandoffRecord:
    """One validated queue record; it carries no execution or approval capability."""

    case_id: str
    request_id: str
    status: str
    proposal: QueryProposal
    created_at: datetime
    claim_by: datetime
    deadline_at: datetime
    evidence_id: str | None


def _check_local(root: Path) -> None:
    text = str(root)
    if text.startswith(("\\\\", "//")):
        raise HandoffError("request queue must be on a local fixed drive")
    resolved = os.path.normcase(os.path.abspath(text))
    for name in ("OneDrive", "OneDriveCommercial", "OneDriveConsumer"):
        synced = os.environ.get(name)
        if synced:
            base = os.path.normcase(os.path.abspath(synced))
            if resolved == base or resolved.startswith(base.rstrip(os.sep) + os.sep):
                raise HandoffError("request queue must not be in a synced folder")
    if os.name == "nt":
        import ctypes

        drive = os.path.splitdrive(os.path.abspath(text))[0] + "\\"
        if ctypes.windll.kernel32.GetDriveTypeW(drive) != 3:  # DRIVE_FIXED
            raise HandoffError("request queue must be on a local fixed drive")


def queue_directory(directory: Path | None = None) -> Path:
    """Return the local, created request folder under the private case directory."""

    root = (directory or case_directory()) / "requests"
    _check_local(root)
    root.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(root, 0o700)
    except OSError:
        pass
    return root


def _requests_path(directory: Path | None) -> Path:
    return (directory or case_directory()) / "requests"


def _record_path(root: Path, case_id: object, request_id: object) -> Path:
    if not isinstance(case_id, str) or not isinstance(request_id, str):
        raise HandoffError("invalid request ID")
    if not _ID.fullmatch(case_id) or not _ID.fullmatch(request_id):
        raise HandoffError("invalid request ID")
    return root / f"{case_id}.req-{request_id}.json"


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_time(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise HandoffError("record timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise HandoffError("record timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise HandoffError("record timestamp is invalid")
    return parsed.astimezone(UTC)


def _payload(record: HandoffRecord) -> bytes:
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


def _parse(raw: bytes, case_id: str, request_id: str) -> HandoffRecord:
    if len(raw) > _MAX_RECORD_BYTES:
        raise HandoffError("record is too large")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HandoffError("record is malformed") from exc
    if not isinstance(data, dict) or set(data) != _KEYS:
        raise HandoffError("record is malformed")
    if type(data["version"]) is not int or data["version"] != 1:
        raise HandoffError("record is malformed")
    if data["case_id"] != case_id or data["request_id"] != request_id:
        raise HandoffError("record is bound to another case or request")
    status = data["status"]
    if not isinstance(status, str) or status not in TERMINAL | ACTIVE:
        raise HandoffError("record status is invalid")
    evidence_id = data["evidence_id"]
    if (status == "released") != (evidence_id is not None):
        raise HandoffError("evidence ID is valid only on released records")
    if evidence_id is not None and (
        not isinstance(evidence_id, str) or not _ID.fullmatch(evidence_id)
    ):
        raise HandoffError("evidence ID is invalid")
    try:
        proposal = QueryProposal.model_validate(data["proposal"])
    except (ValidationError, TypeError, ValueError) as exc:
        raise HandoffError("record proposal is invalid") from exc
    if proposal.operation == "reject":
        raise HandoffError("rejected proposals are never queued")
    created_at = _parse_time(data["created_at"])
    claim_by = _parse_time(data["claim_by"])
    deadline_at = _parse_time(data["deadline_at"])
    if not created_at < claim_by <= deadline_at:
        raise HandoffError("record timestamps are inconsistent")
    return HandoffRecord(
        case_id, request_id, status, proposal, created_at, claim_by, deadline_at, evidence_id
    )


def _read(path: Path, case_id: str, request_id: str) -> HandoffRecord:
    for attempt in range(_READ_ATTEMPTS):
        try:
            with path.open("rb") as stream:
                raw = stream.read(_MAX_RECORD_BYTES + 1)
            return _parse(raw, case_id, request_id)
        except PermissionError:  # Windows sharing violation during an owner replace
            if attempt == _READ_ATTEMPTS - 1:
                raise
            time.sleep(_RETRY_SECONDS)
    raise HandoffError("record is unavailable")


def _temp_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")


def _write_temp(path: Path, payload: bytes) -> Path:
    temp = _temp_path(path)
    with temp.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    return temp


def _write_new(path: Path, payload: bytes) -> None:
    """Create ``path`` atomically; never overwrite an existing record."""

    temp = _write_temp(path, payload)
    try:
        os.link(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _replace(path: Path, payload: bytes) -> None:
    temp = _write_temp(path, payload)
    try:
        for attempt in range(_REPLACE_ATTEMPTS):
            try:
                os.replace(temp, path)
                return
            except PermissionError:  # a reader holds the record open on Windows
                if attempt == _REPLACE_ATTEMPTS - 1:
                    raise HandoffError("request record update failed") from None
                time.sleep(_RETRY_SECONDS)
    finally:
        temp.unlink(missing_ok=True)


def _effective_status(record: HandoffRecord, now: datetime) -> str:
    if record.status in TERMINAL:
        return record.status
    if now >= record.deadline_at or (record.status == "queued" and now >= record.claim_by):
        return "expired"
    return record.status


def _records(root: Path, pattern: str) -> list[HandoffRecord]:
    found: list[HandoffRecord] = []
    for path in root.glob(pattern):
        match = _RECORD_NAME.fullmatch(path.name)
        if match is None:
            continue
        try:
            found.append(_read(path, match.group(1), match.group(2)))
        except (HandoffError, OSError):
            continue
    return found


def enqueue_request(
    case_id: str,
    proposal: QueryProposal,
    *,
    claim_seconds: int,
    deadline_minutes: int,
    directory: Path | None = None,
    now: datetime | None = None,
) -> tuple[Literal["queued", "busy"], str]:
    """Queue one validated typed proposal for local supervision; never executes it."""

    if not isinstance(proposal, QueryProposal) or proposal.operation == "reject":
        raise HandoffError("only a validated read proposal can be queued")
    if not isinstance(case_id, str) or not _ID.fullmatch(case_id):
        raise HandoffError("invalid case ID")
    now = now or datetime.now(UTC)
    root = queue_directory(directory)
    for record in _records(root, f"{case_id}.req-*.json"):
        if _effective_status(record, now) in ACTIVE:
            return "busy", record.request_id
    deadline_at = now + timedelta(minutes=deadline_minutes)
    claim_by = min(now + timedelta(seconds=claim_seconds), deadline_at)
    request_id = secrets.token_hex(12)
    record = HandoffRecord(
        case_id, request_id, "queued", proposal, now, claim_by, deadline_at, None
    )
    _write_new(_record_path(root, case_id, request_id), _payload(record))
    return "queued", request_id


def request_status(
    case_id: str,
    request_id: str,
    directory: Path | None = None,
    now: datetime | None = None,
) -> dict[str, str]:
    """Return only an allow-listed status and, after release, the opaque evidence ID."""

    try:
        path = _record_path(_requests_path(directory), case_id, request_id)
        record = _read(path, case_id, request_id)
    except PermissionError:
        return {"status": "unavailable"}
    except (HandoffError, OSError):
        return {"status": "unknown"}
    status = _effective_status(record, now or datetime.now(UTC))
    if status == "released" and record.evidence_id is not None:
        return {"status": status, "evidence_id": record.evidence_id}
    return {"status": status}


def cleanup_requests(directory: Path | None = None, now: datetime | None = None) -> int:
    """Delete records whose deadline passed over 24 h ago, plus stale junk files."""

    now = now or datetime.now(UTC)
    root = _requests_path(directory)
    if not root.is_dir():
        return 0
    removed = 0
    wall_clock = time.time()

    def unlink(path: Path) -> None:
        nonlocal removed
        try:
            path.unlink()
            removed += 1
        except FileNotFoundError:
            pass
        except OSError:
            pass

    for path in list(root.iterdir()):
        try:
            age_seconds = wall_clock - path.stat().st_mtime
        except OSError:
            continue
        match = _RECORD_NAME.fullmatch(path.name)
        if match is not None:
            try:
                record = _read(path, match.group(1), match.group(2))
            except (HandoffError, OSError):
                if age_seconds > _RETENTION.total_seconds():
                    unlink(path)
                continue
            if now >= record.deadline_at + _RETENTION:
                unlink(path)
                unlink(path.with_suffix(".claim"))
        elif path.name.startswith(".") and path.name.endswith(".tmp"):
            if age_seconds > _TEMP_RETENTION_SECONDS:
                unlink(path)
        elif _CLAIM_NAME.fullmatch(path.name):
            if not path.with_suffix(".json").exists() and age_seconds > _RETENTION.total_seconds():
                unlink(path)
    return removed


class RequestSupervisor:
    """GUI-side sole claimer and owner. Claims only requests created after it started."""

    def __init__(self, directory: Path | None = None, started_at: datetime | None = None) -> None:
        self._directory = directory
        self._root = queue_directory(directory)
        self._started_at = started_at or datetime.now(UTC)
        self._lock = threading.Lock()
        self._consumed: set[str] = set()
        self._owned: dict[str, HandoffRecord] = {}

    def _claim(self, record: HandoffRecord) -> HandoffRecord | None:
        marker = self._root / f"{record.case_id}.req-{record.request_id}.claim"
        try:
            with marker.open("xb"):
                pass
        except FileExistsError:
            return None
        self._consumed.add(record.request_id)
        claimed = replace(record, status="claimed")
        _replace(_record_path(self._root, record.case_id, record.request_id), _payload(claimed))
        self._owned[record.request_id] = claimed
        return claimed

    def claim_next(self, case_id: str, now: datetime | None = None) -> HandoffRecord | None:
        """Claim the oldest fresh request for ``case_id``; reject same-case duplicates."""

        if not isinstance(case_id, str) or not _ID.fullmatch(case_id):
            return None
        now = now or datetime.now(UTC)
        with self._lock:
            if any(record.status in ACTIVE for record in self._owned.values()):
                return None
            candidates = [
                record
                for record in _records(self._root, f"{case_id}.req-*.json")
                if record.request_id not in self._consumed
                and record.status == "queued"
                and _effective_status(record, now) == "queued"
                and record.created_at >= self._started_at
            ]
            candidates.sort(key=lambda record: (record.created_at, record.request_id))
            chosen: HandoffRecord | None = None
            for record in candidates:
                claimed = self._claim(record)
                if claimed is None:
                    continue
                if chosen is None:
                    chosen = claimed
                else:
                    self._transition(claimed.request_id, "rejected", None)
            return chosen

    def _transition(self, request_id: str, status: str, evidence_id: str | None) -> HandoffRecord:
        current = self._owned.get(request_id)
        if current is None:
            raise HandoffError("request is not owned by this supervisor")
        if status not in _TRANSITIONS.get(current.status, frozenset()):
            raise HandoffError("illegal request state transition")
        if (status == "released") != (evidence_id is not None):
            raise HandoffError("an evidence ID accompanies release only")
        if evidence_id is not None and not _ID.fullmatch(evidence_id):
            raise HandoffError("evidence ID is invalid")
        updated = replace(current, status=status, evidence_id=evidence_id)
        _replace(_record_path(self._root, current.case_id, request_id), _payload(updated))
        self._owned[request_id] = updated
        return updated

    def transition(
        self, request_id: str, status: str, *, evidence_id: str | None = None
    ) -> HandoffRecord:
        """Move an owned request along the documented state machine."""

        with self._lock:
            return self._transition(request_id, status, evidence_id)

    def current(self, request_id: str) -> HandoffRecord | None:
        """Return this supervisor's view of an owned request."""

        with self._lock:
            return self._owned.get(request_id)

    def shutdown(self) -> None:
        """Cancel owned in-flight requests; closing never approves anything."""

        with self._lock:
            for request_id, record in list(self._owned.items()):
                if record.status in ACTIVE:
                    try:
                        self._transition(request_id, "cancelled", None)
                    except (HandoffError, OSError):
                        continue
