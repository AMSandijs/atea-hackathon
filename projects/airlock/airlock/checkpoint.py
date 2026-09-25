"""Rich approval checkpoint shown before any Airlock transmission."""

from __future__ import annotations

import difflib

from rich.console import Console
from rich.prompt import Confirm
from rich.table import Table

from .config import Policy
from .models import Sanitized


def render_checkpoint(original: str, sanitized: Sanitized, policy: Policy, console: Console) -> None:
    """Render findings, uncertainty, and the exact text planned for transmission."""

    del policy
    console.print("[bold]Airlock checkpoint[/bold]")
    if sanitized.blocked:
        console.print("[bold red]Blocked findings detected — rotate the credential before retrying.[/bold red]")

    table = Table("Tier", "Entity", "Found", "Stand-in", "Confidence")
    inverse = {original: stand_in for stand_in, original in sanitized.mapping.items()}
    for tier in ("block", "swap", "pass"):
        for finding in (item for item in sanitized.findings if item.tier == tier):
            stand_in = inverse.get(finding.text, "[BLOCKED]" if tier == "block" else "—")
            uncertain = " [yellow]UNCERTAIN[/yellow]" if finding in sanitized.low_confidence else ""
            table.add_row(tier, finding.entity_type, finding.text, stand_in, f"{finding.score:.2f}{uncertain}")
    if table.row_count:
        console.print(table)
    console.print("[bold]Transmitted text[/bold]")
    diff = "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            sanitized.text.splitlines(keepends=True),
            fromfile="original",
            tofile="sanitized",
        )
    )
    console.print(diff or "(unchanged)")


def checkpoint(
    original: str,
    sanitized: Sanitized,
    policy: Policy,
    console: Console | None = None,
    decision: bool | None = None,
) -> bool:
    """Render the checkpoint and return the explicit approval decision."""

    active_console = console or Console()
    render_checkpoint(original, sanitized, policy, active_console)
    if sanitized.blocked:
        return False
    if decision is not None:
        return decision
    return Confirm.ask("Approve transmission?", console=active_console, default=False)
