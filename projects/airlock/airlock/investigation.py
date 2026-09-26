"""One locally supervised planner-to-Azure-to-approved-evidence turn."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from .broker import BrokerError, QueryReview, case_capabilities, execute_query
from .cases import release_evidence
from .config import Policy
from .handoff import TERMINAL, HandoffError, HandoffRecord, RequestSupervisor
from .models import Sanitized
from .planner import QueryProposal, plan_query

TurnStatus = Literal["proposal_rejected", "query_denied", "result_not_released", "released"]


@dataclass(frozen=True)
class InvestigationTurn:
    """Outcome of one proposal, one approved read, and its separate release gate."""

    proposal: QueryProposal
    status: TurnStatus
    evidence_id: str | None = None


def plan_investigation(
    case_id: str,
    goal: str,
    policy: Policy,
    directory: Path | None = None,
) -> QueryProposal:
    """Plan one typed read from approved aliases/operations only; never calls Azure."""

    return plan_query(goal, case_capabilities(case_id, directory), policy)


def run_investigation_proposal(
    case_id: str,
    proposal: QueryProposal,
    policy: Policy,
    *,
    approve_query: Callable[[QueryReview], bool] | None,
    result_decision: bool | None = None,
    approve_result: Callable[[str, Sanitized], bool] | None = None,
    allow_rules_only: bool = False,
    directory: Path | None = None,
) -> InvestigationTurn:
    """Execute one untrusted proposal through the broker and the separate release gate."""

    if result_decision is not None and approve_result is not None:
        raise ValueError("supply either a result decision or a local review callback")
    if proposal.operation == "reject":
        return InvestigationTurn(proposal, "proposal_rejected")

    raw_result = execute_query(
        case_id,
        proposal,
        approve_query=approve_query,
        directory=directory,
    )
    if raw_result is None:
        return InvestigationTurn(proposal, "query_denied")

    evidence_id = release_evidence(
        case_id,
        raw_result,
        policy,
        decision=result_decision,
        approve_result=approve_result,
        allow_rules_only=allow_rules_only,
        directory=directory,
    )
    if evidence_id is None:
        return InvestigationTurn(proposal, "result_not_released")
    return InvestigationTurn(proposal, "released", evidence_id)


def run_investigation_turn(
    case_id: str,
    goal: str,
    policy: Policy,
    *,
    approve_query: Callable[[QueryReview], bool] | None,
    result_decision: bool | None = None,
    approve_result: Callable[[str, Sanitized], bool] | None = None,
    allow_rules_only: bool = False,
    directory: Path | None = None,
) -> InvestigationTurn:
    """Run one bounded investigation turn; only approved sanitized evidence is released."""

    if result_decision is not None and approve_result is not None:
        raise ValueError("supply either a result decision or a local review callback")
    return run_investigation_proposal(
        case_id,
        plan_investigation(case_id, goal, policy, directory),
        policy,
        approve_query=approve_query,
        result_decision=result_decision,
        approve_result=approve_result,
        allow_rules_only=allow_rules_only,
        directory=directory,
    )


def _now() -> datetime:
    return datetime.now(UTC)


def run_queued_request(
    supervisor: RequestSupervisor,
    record: HandoffRecord,
    policy: Policy,
    *,
    approve_query: Callable[[QueryReview], bool],
    approve_result: Callable[[str, Sanitized], bool],
    allow_rules_only: bool = False,
    directory: Path | None = None,
) -> str:
    """Supervise one claimed Copilot request and write exactly one terminal state.

    Approvals come only from the supplied local callbacks. Queue writes wrap them, so a
    cancelled or expired request makes the broker/release gates deny. Never raises.
    """

    request_id = record.request_id
    seen = {"query_asked": False, "blocked": False, "expired": False}

    def in_time() -> bool:
        if _now() < record.deadline_at:
            return True
        seen["expired"] = True
        return False

    def query_gate(review: QueryReview) -> bool:
        seen["query_asked"] = True
        supervisor.transition(request_id, "awaiting_query_approval")
        if approve_query(review) is not True or not in_time():
            return False
        supervisor.transition(request_id, "running")
        return True

    def result_gate(raw_result: str, sanitized: Sanitized) -> bool:
        if sanitized.blocked:
            seen["blocked"] = True
        if not in_time():
            return False
        supervisor.transition(request_id, "awaiting_result_review")
        return approve_result(raw_result, sanitized) is True and in_time()

    final = "failed"
    evidence_id: str | None = None
    try:
        if not in_time():
            final = "expired"
        else:
            turn = run_investigation_proposal(
                record.case_id,
                record.proposal,
                policy,
                approve_query=query_gate,
                approve_result=result_gate,
                allow_rules_only=allow_rules_only,
                directory=directory,
            )
            if turn.status == "released" and turn.evidence_id is not None:
                final, evidence_id = "released", turn.evidence_id
            elif turn.status == "proposal_rejected":
                final = "rejected"
            elif seen["expired"]:
                final = "expired"
            elif seen["blocked"]:
                final = "blocked"
            else:
                final = "denied"
    except BrokerError:
        final = "failed" if seen["query_asked"] else "rejected"
    except Exception:  # noqa: BLE001 — every other failure is a generic, closed outcome.
        final = "failed"

    current = supervisor.current(request_id)
    if current is None:
        return "failed"
    if current.status in TERMINAL:
        return current.status
    for status in (final, "failed"):
        try:
            supervisor.transition(
                request_id, status, evidence_id=evidence_id if status == "released" else None
            )
            return status
        except (HandoffError, OSError):
            continue
    return "failed"
