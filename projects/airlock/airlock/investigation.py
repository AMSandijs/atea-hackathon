"""One locally supervised planner-to-Azure-to-approved-evidence turn."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .broker import QueryReview, case_capabilities, execute_query
from .cases import release_evidence
from .config import Policy
from .planner import QueryProposal, plan_query

TurnStatus = Literal["proposal_rejected", "query_denied", "result_not_released", "released"]


@dataclass(frozen=True)
class InvestigationTurn:
    """Outcome of one proposal, one approved read, and its separate release gate."""

    proposal: QueryProposal
    status: TurnStatus
    evidence_id: str | None = None


def run_investigation_turn(
    case_id: str,
    goal: str,
    policy: Policy,
    *,
    approve_query: Callable[[QueryReview], bool] | None,
    result_decision: bool | None = None,
    allow_rules_only: bool = False,
    directory: Path | None = None,
) -> InvestigationTurn:
    """Run one bounded investigation turn; only approved sanitized evidence is released."""

    capabilities = case_capabilities(case_id, directory)
    proposal = plan_query(goal, capabilities, policy)
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
        allow_rules_only=allow_rules_only,
        directory=directory,
    )
    if evidence_id is None:
        return InvestigationTurn(proposal, "result_not_released")
    return InvestigationTurn(proposal, "released", evidence_id)
