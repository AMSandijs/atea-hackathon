"""Local stdio MCP front door: approved sanitized cases/evidence and queued read requests.

Copilot can ask for one supervised read by case ID and alias-only goal. Planning happens
locally; execution and both approvals happen only in the local GUI. Responses carry an
allow-listed status and opaque IDs, never proposals, resource IDs, or error text.
"""

from __future__ import annotations

from mcp.server import MCPServer

from .cases import read_case as _read_case
from .cases import read_evidence as _read_evidence
from .config import load_policy
from .handoff import HandoffError, enqueue_request, queue_directory, request_status
from .investigation import plan_investigation

_MAX_GOAL_CHARS = 2_000

mcp = MCPServer("Local AI Airlock")


@mcp.tool()
def read_case(case_id: str) -> str:
    """Read an operator-approved, sanitized Azure investigation by opaque case ID."""

    return _read_case(case_id)


@mcp.tool()
def read_evidence(case_id: str, evidence_id: str) -> str:
    """Read separately approved, sanitized Azure evidence for an approved case."""

    return _read_evidence(case_id, evidence_id)


@mcp.tool()
def request_investigation(case_id: str, goal: str) -> dict[str, str]:
    """Ask the local Airlock supervisor for one bounded read on an approved case.

    Name exactly one approved alias (for example VM_1) in the goal; never include real
    resource names or IDs. The operator approves the query and the sanitized result
    locally. Poll investigation_status, then read released evidence with read_evidence.
    """

    try:
        _read_case(case_id)
    except Exception:  # noqa: BLE001 — any case problem is a generic rejection.
        return {"status": "proposal_rejected"}
    if not isinstance(goal, str) or not goal.strip() or len(goal) > _MAX_GOAL_CHARS:
        return {"status": "proposal_rejected"}
    try:
        queue_directory()
    except (HandoffError, OSError):
        return {"status": "supervisor_unavailable"}
    try:
        policy = load_policy()
        proposal = plan_investigation(case_id, goal, policy)
    except Exception:  # noqa: BLE001 — planner/scope errors must not reach Copilot.
        return {"status": "proposal_rejected"}
    if proposal.operation == "reject":
        return {"status": "proposal_rejected"}
    try:
        status, request_id = enqueue_request(
            case_id,
            proposal,
            claim_seconds=policy.investigation.request_claim_seconds,
            deadline_minutes=policy.investigation.request_deadline_minutes,
        )
    except (HandoffError, OSError):
        return {"status": "supervisor_unavailable"}
    return {"status": status, "request_id": request_id}


@mcp.tool()
def investigation_status(case_id: str, request_id: str) -> dict[str, str]:
    """Return the status of a requested read and, once released, its evidence ID."""

    return request_status(case_id, request_id)


if __name__ == "__main__":
    mcp.run(transport="stdio")
