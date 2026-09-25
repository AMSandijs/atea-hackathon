"""Deterministic authorization gate for future fixed Azure read adapters."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from .cases import read_case
from .planner import PlannerError, QueryProposal, validate_proposal
from .scope import CaseScope, ScopeError, _read_scope


class BrokerError(RuntimeError):
    """A local query proposal could not be authorized."""


@dataclass(frozen=True)
class QueryReview:
    """Local-only details for approving one read against a real resource."""

    case_id: str
    target_alias: str
    resource_id: str
    operation: str
    time_range_minutes: int


@dataclass(frozen=True)
class AuthorizedRead:
    """Internal typed capability; only a future fixed adapter may consume it."""

    case_id: str
    target_alias: str
    resource_id: str = field(repr=False)
    operation: str
    time_range_minutes: int


def _active_scope(case_id: str, directory: Path | None) -> CaseScope:
    try:
        read_case(case_id, directory)
        scope = _read_scope(case_id, directory)
    except (OSError, ValueError, TypeError, ScopeError) as exc:
        raise BrokerError("approved case scope is unavailable or invalid") from exc
    if scope.expires_at <= datetime.now(UTC):
        raise BrokerError("approved case scope has expired")
    return scope


def case_capabilities(case_id: str, directory: Path | None = None) -> dict[str, tuple[str, ...]]:
    """Return only aliases and derived operations for local planning."""

    scope = _active_scope(case_id, directory)
    return {target.alias: target.operations for target in scope.targets}


def authorize_query(
    case_id: str,
    proposal: QueryProposal,
    *,
    approve_query: Callable[[QueryReview], bool] | None,
    directory: Path | None = None,
) -> AuthorizedRead | None:
    """Revalidate a planner proposal and return a capability only after local approval.

    A rejected proposal or operator denial returns ``None``. This function never
    starts a subprocess, calls Azure, sanitizes evidence, or publishes a result.
    """

    if not callable(approve_query):
        raise BrokerError("trusted local query approval is required")
    scope = _active_scope(case_id, directory)
    capabilities = {target.alias: target.operations for target in scope.targets}
    try:
        checked = validate_proposal(proposal.model_dump_json(), capabilities)
    except (PlannerError, AttributeError, TypeError) as exc:
        raise BrokerError("query proposal is invalid for the approved case scope") from exc
    if checked.operation == "reject":
        return None
    target = next((item for item in scope.targets if item.alias == checked.target_alias), None)
    if target is None or checked.operation not in target.operations:
        raise BrokerError("query proposal is outside the approved case scope")

    review = QueryReview(
        case_id=case_id,
        target_alias=target.alias,
        resource_id=target.resource_id,
        operation=checked.operation,
        time_range_minutes=checked.time_range_minutes,
    )
    try:
        accepted = approve_query(review)
    except Exception as exc:
        raise BrokerError("local query approval failed; no Azure query was authorized") from exc
    if accepted is not True:
        return None
    return AuthorizedRead(
        case_id=case_id,
        target_alias=target.alias,
        resource_id=target.resource_id,
        operation=checked.operation,
        time_range_minutes=checked.time_range_minutes,
    )
