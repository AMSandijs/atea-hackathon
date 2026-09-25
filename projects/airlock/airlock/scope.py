"""Private, operator-approved resource scope for one sanitized case."""

from __future__ import annotations

import json
import os
import re
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .cases import case_directory, read_case

_CASE_ID = re.compile(r"[0-9a-f]{24}\Z")
_ALIAS = re.compile(r"[A-Z]{1,8}_[0-9]{1,6}\Z")
_SUBSCRIPTION_ID = re.compile(r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}\Z")
_SEGMENT = re.compile(r"[A-Za-z0-9._-]{1,128}\Z")
_PROVIDER = re.compile(r"[A-Za-z][A-Za-z0-9.]{1,127}\Z")
_MAX_TARGETS = 32
_MAX_SCOPE_MINUTES = 1_440


class ScopeError(ValueError):
    """The private case scope is invalid or could not be approved."""


@dataclass(frozen=True)
class ScopeTarget:
    """One private alias-to-resource binding and its derived read operation."""

    alias: str
    resource_id: str
    operations: tuple[str, ...]


@dataclass(frozen=True)
class ScopeReview:
    """Local-only scope details presented for explicit operator approval."""

    case_id: str
    expires_at: datetime
    targets: tuple[ScopeTarget, ...]


@dataclass(frozen=True)
class CaseScope:
    """Validated private scope loaded from local case storage."""

    case_id: str
    created_at: datetime
    expires_at: datetime
    targets: tuple[ScopeTarget, ...]


def _scope_path(case_id: str, directory: Path | None) -> Path:
    if not isinstance(case_id, str) or not _CASE_ID.fullmatch(case_id):
        raise ScopeError("invalid case ID")
    return (directory or case_directory()) / f"{case_id}.scope.json"


def _operations_for_resource_id(resource_id: str) -> tuple[str, ...]:
    if (
        not isinstance(resource_id, str)
        or len(resource_id) > 1_024
        or not resource_id.startswith("/")
    ):
        raise ScopeError("resource ID is invalid or unsupported")
    parts = resource_id[1:].split("/")
    if (
        len(parts) < 8
        or parts[0].casefold() != "subscriptions"
        or not _SUBSCRIPTION_ID.fullmatch(parts[1])
        or parts[2].casefold() != "resourcegroups"
        or parts[4].casefold() != "providers"
        or not _PROVIDER.fullmatch(parts[5])
        or len(parts[6:]) % 2 != 0
        or any(not _SEGMENT.fullmatch(segment) for segment in parts[2:4] + parts[6:])
    ):
        raise ScopeError("resource ID is invalid or unsupported")
    try:
        uuid.UUID(parts[1])
    except ValueError as exc:
        raise ScopeError("resource ID is invalid or unsupported") from exc

    namespace = parts[5].casefold()
    resource_types = tuple(parts[index].casefold() for index in range(6, len(parts), 2))
    if namespace == "microsoft.compute" and resource_types == ("virtualmachines",):
        return ("vm_cpu",)
    if namespace == "microsoft.insights" and resource_types == ("components",):
        return ("app_failures",)
    if namespace == "microsoft.logic" and resource_types == ("workflows",):
        return ("logic_runs",)
    if namespace == "microsoft.sql" and resource_types == ("servers", "databases"):
        return ("sql_metrics",)
    raise ScopeError("resource ID is invalid or unsupported")


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ScopeError("private case scope is invalid")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ScopeError("private case scope is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ScopeError("private case scope is invalid")
    return parsed.astimezone(UTC)


def _read_scope(case_id: str, directory: Path | None = None) -> CaseScope:
    path = _scope_path(case_id, directory)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScopeError("private case scope is missing or unreadable") from exc
    if not isinstance(raw, dict) or set(raw) != {
        "version",
        "case_id",
        "created_at",
        "expires_at",
        "targets",
    }:
        raise ScopeError("private case scope is invalid")
    if type(raw["version"]) is not int or raw["version"] != 1 or raw["case_id"] != case_id:
        raise ScopeError("private case scope is invalid")
    created_at = _parse_timestamp(raw["created_at"])
    expires_at = _parse_timestamp(raw["expires_at"])
    if expires_at <= created_at or expires_at - created_at > timedelta(minutes=_MAX_SCOPE_MINUTES):
        raise ScopeError("private case scope is invalid")
    raw_targets = raw["targets"]
    if not isinstance(raw_targets, list) or not 1 <= len(raw_targets) <= _MAX_TARGETS:
        raise ScopeError("private case scope is invalid")

    targets: list[ScopeTarget] = []
    aliases: set[str] = set()
    resource_ids: set[str] = set()
    for item in raw_targets:
        if not isinstance(item, dict) or set(item) != {"alias", "resource_id", "operations"}:
            raise ScopeError("private case scope is invalid")
        alias, resource_id = item["alias"], item["resource_id"]
        operations = item["operations"]
        if not isinstance(alias, str) or not _ALIAS.fullmatch(alias):
            raise ScopeError("private case scope is invalid")
        derived = _operations_for_resource_id(resource_id)
        if (
            alias in aliases
            or resource_id.casefold() in resource_ids
            or not isinstance(operations, list)
            or tuple(operations) != derived
        ):
            raise ScopeError("private case scope is invalid")
        aliases.add(alias)
        resource_ids.add(resource_id.casefold())
        targets.append(ScopeTarget(alias, resource_id, derived))
    return CaseScope(case_id, created_at, expires_at, tuple(targets))


def create_case_scope(
    case_id: str,
    resource_ids: Mapping[str, str],
    *,
    approve_scope: Callable[[ScopeReview], bool] | None,
    expires_in_minutes: int = _MAX_SCOPE_MINUTES,
    directory: Path | None = None,
) -> CaseScope:
    """Bind approved aliases to resources after explicit local operator approval.

    Supported operations are inferred from ARM provider/resource types and cannot be
    supplied or expanded by the planner. Existing scope files are never overwritten.
    """

    if not callable(approve_scope):
        raise ScopeError("trusted local scope approval is required")
    if type(expires_in_minutes) is not int or not 1 <= expires_in_minutes <= _MAX_SCOPE_MINUTES:
        raise ScopeError("scope duration must be between 1 and 1440 minutes")
    if not isinstance(resource_ids, Mapping) or not 1 <= len(resource_ids) <= _MAX_TARGETS:
        raise ScopeError("scope must contain between 1 and 32 targets")
    try:
        read_case(case_id, directory)
    except (OSError, ValueError, TypeError) as exc:
        raise ScopeError("scope requires an approved sanitized case") from exc

    targets: list[ScopeTarget] = []
    seen_resource_ids: set[str] = set()
    for alias, resource_id in resource_ids.items():
        if not isinstance(alias, str) or not _ALIAS.fullmatch(alias):
            raise ScopeError("scope alias is invalid")
        operations = _operations_for_resource_id(resource_id)
        if resource_id.casefold() in seen_resource_ids:
            raise ScopeError("scope resource IDs must be unique")
        seen_resource_ids.add(resource_id.casefold())
        targets.append(ScopeTarget(alias, resource_id, operations))
    targets.sort(key=lambda target: target.alias)

    created_at = datetime.now(UTC)
    expires_at = created_at + timedelta(minutes=expires_in_minutes)
    review = ScopeReview(case_id, expires_at, tuple(targets))
    try:
        accepted = approve_scope(review)
    except Exception as exc:
        raise ScopeError("local scope approval failed; scope was not created") from exc
    if accepted is not True:
        raise ScopeError("scope was not approved")

    root = directory or case_directory()
    root.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(root, 0o700)
    except OSError:
        pass
    payload = {
        "version": 1,
        "case_id": case_id,
        "created_at": created_at.isoformat().replace("+00:00", "Z"),
        "expires_at": expires_at.isoformat().replace("+00:00", "Z"),
        "targets": [
            {
                "alias": target.alias,
                "resource_id": target.resource_id,
                "operations": list(target.operations),
            }
            for target in targets
        ],
    }
    path = _scope_path(case_id, root)
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, sort_keys=True, indent=2) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    except FileExistsError as exc:
        raise ScopeError("case scope already exists; create a new case to change scope") from exc
    return CaseScope(case_id, created_at, expires_at, tuple(targets))
