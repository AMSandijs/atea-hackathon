"""Command-line entry point for the Airlock build."""

import json
import os
import re
import secrets
import time
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.prompt import Confirm

from .azure import capture_resource
from .broker import QueryReview
from .cases import prepare_case, restore_case
from .checkpoint import checkpoint
from .config import load_policy
from .detect.model import local_endpoint
from .gateway import send
from .investigation import InvestigationTurn, run_investigation_turn
from .models import AirlockResult
from .rehydrate import rehydrate
from .sanitize import sanitize
from .scope import ScopeReview, create_case_scope
from .vault import Vault

app = typer.Typer(help="Local AI Airlock — inspect and safely transform model requests.")


def _append_run(result: AirlockResult, policy_version: int, approved: bool) -> None:
    log_path = Path(os.environ.get("AIRLOCK_RUN_LOG", "runs.jsonl"))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    for finding in result.sanitized.findings:
        counts[finding.entity_type] = counts.get(finding.entity_type, 0) + 1
    record = {
        "timestamp": time.time(),
        "policy_version": policy_version,
        "counts": counts,
        "blocked": len(result.sanitized.blocked),
        "approved": approved,
        "latency_ms": result.latency_ms,
        "unmapped": len(result.unmapped),
    }
    with log_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, sort_keys=True) + "\n")


def run_ask(
    source: str,
    prompt: str,
    policy_path: Path | None = None,
    approval: bool | None = None,
) -> AirlockResult:
    """Run the request path, using the gateway's offline echo when unconfigured."""

    policy = load_policy(policy_path)
    cloud_enabled = bool(os.environ.get(policy.gateway.endpoint_env))
    if cloud_enabled and local_endpoint() is None:
        raise ValueError("cloud gateway requires a configured loopback local model")
    key = os.environ.get("AIRLOCK_VAULT_KEY", "").encode() or secrets.token_bytes(32)
    vault_path = Path(os.environ.get("AIRLOCK_VAULT_PATH", "vault-session.json"))
    started = time.perf_counter()
    combined = source if prompt in source else f"{prompt}\n\n{source}"
    sanitized = sanitize(combined, policy, Vault(key, vault_path), strict_model=cloud_enabled)
    sanitize_ms = int((time.perf_counter() - started) * 1000)
    if sanitized.blocked:
        result = AirlockResult("", sanitized, "", "", [], {"sanitize": sanitize_ms})
        _append_run(result, policy.version, False)
        return result
    if approval is None:
        approval = checkpoint(combined, sanitized, policy)
    if not approval:
        result = AirlockResult("", sanitized, "", "", [], {"sanitize": sanitize_ms})
        _append_run(result, policy.version, False)
        return result
    received, gateway_ms = send(sanitized, policy)
    answer, unmapped = rehydrate(received, sanitized.mapping)
    result = AirlockResult(
        answer,
        sanitized,
        sanitized.text,
        received,
        unmapped,
        {"sanitize": sanitize_ms, "gateway": gateway_ms},
    )
    _append_run(result, policy.version, True)
    return result


@app.command()
def scan(path: Path) -> None:
    """Render the sanitization checkpoint for a file without sending it."""

    policy = load_policy()
    source = path.read_text(encoding="utf-8")
    key = os.environ.get("AIRLOCK_VAULT_KEY", "").encode() or secrets.token_bytes(32)
    vault_path = Path(os.environ.get("AIRLOCK_VAULT_PATH", "vault-session.json"))
    sanitized = sanitize(source, policy, Vault(key, vault_path))
    checkpoint(source, sanitized, policy, decision=False)


@app.command()
def ask(prompt: str, file: Annotated[Path | None, typer.Option("--file")] = None) -> None:
    """Sanitize a prompt and optional file, send it through the gateway, and restore the answer."""

    source = prompt
    if file:
        source += "\n\n" + file.read_text(encoding="utf-8")
    try:
        result = run_ask(source, prompt)
    except (RuntimeError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    if result.sanitized.blocked:
        typer.echo("Request blocked: rotate the exposed credential before retrying.", err=True)
        raise typer.Exit(code=2)
    typer.echo(f"sent={result.sent}")
    typer.echo(f"received={result.received}")
    typer.echo(f"answer={result.answer}")
    typer.echo(f"unmapped={len(result.unmapped)}")


@app.command(name="eval")
def evaluate(
    with_model: Annotated[bool, typer.Option("--with-model")] = False,
    model_name: Annotated[str | None, typer.Option("--model-name")] = None,
    model_provider: Annotated[str | None, typer.Option("--model-provider")] = None,
) -> None:
    """Score the detector corpus and write a dated JSON report."""

    from eval.score import evaluate_corpus, print_summary

    try:
        if (model_name or model_provider) and not with_model:
            raise ValueError("model overrides require --with-model")
        policy = load_policy()
        if model_name:
            policy.model.name = model_name
        if model_provider:
            policy.model.provider = model_provider
        result = evaluate_corpus(policy=policy, with_model=with_model)
    except (RuntimeError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    print_summary(result)
    typer.echo(f"results={result['output']}")


@app.command()
def prepare(file: Path, rules_only: Annotated[bool, typer.Option("--rules-only")] = False) -> None:
    """Review an Azure snapshot locally and create an approved Copilot case."""

    source = file.read_text(encoding="utf-8")
    if rules_only:
        typer.echo("Rules-only mode: no local prose-model sweep was run.", err=True)
    try:
        case_id = prepare_case(source, load_policy(), allow_rules_only=rules_only)
    except (RuntimeError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    if case_id is None:
        typer.echo("Case was blocked or not approved; nothing was released.", err=True)
        raise typer.Exit(code=2)
    typer.echo(f"case_id={case_id}")


@app.command()
def capture(
    resource_id: str,
    rules_only: Annotated[bool, typer.Option("--rules-only")] = False,
    metric: Annotated[str | None, typer.Option("--metric")] = None,
) -> None:
    """Read one Azure resource locally, then review a sanitized Copilot case."""

    try:
        source = capture_resource(resource_id, metric=metric)
        case_id = prepare_case(source, load_policy(), allow_rules_only=rules_only)
    except (RuntimeError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    if case_id is None:
        typer.echo("Case was blocked or not approved; nothing was released.", err=True)
        raise typer.Exit(code=2)
    typer.echo(f"case_id={case_id}")


def _confirm_scope(review: ScopeReview) -> bool:
    console = Console(stderr=True)
    console.print("[bold]Private Azure scope review[/bold]")
    console.print(f"Case: {review.case_id}")
    console.print(f"Expires: {review.expires_at.isoformat()}")
    for target in review.targets:
        console.print(f"{target.alias}: {target.resource_id} ({', '.join(target.operations)})")
    return Confirm.ask("Approve and save this scope?", console=console, default=False)


def _confirm_query(review: QueryReview) -> bool:
    console = Console(stderr=True)
    console.print("[bold]Azure read approval[/bold]")
    console.print(f"Target alias: {review.target_alias}")
    console.print(f"Real resource: {review.resource_id}")
    console.print(f"Operation: {review.operation}")
    console.print(f"Time range: last {review.time_range_minutes} minutes")
    return Confirm.ask("Run this read-only Azure query?", console=console, default=False)


@app.command(name="scope")
def approve_scope(
    case_id: str,
    alias: Annotated[
        list[str] | None, typer.Option("--alias", help="Repeat an alias such as VM_1.")
    ] = None,
    expires_in_minutes: Annotated[
        int, typer.Option("--expires-in-minutes", min=1, max=1_440)
    ] = 240,
) -> None:
    """Approve a private alias-to-resource scope for an existing case."""

    resource_ids: dict[str, str] = {}
    aliases = alias or []
    if not aliases or any(not re.fullmatch(r"[A-Z]{1,8}_[0-9]{1,6}", item) for item in aliases):
        typer.echo("Supply one or more aliases with --alias, for example --alias VM_1.", err=True)
        raise typer.Exit(code=2)
    if len(set(aliases)) != len(aliases):
        typer.echo("Scope aliases must be unique.", err=True)
        raise typer.Exit(code=2)
    try:
        for item in aliases:
            resource_ids[item] = typer.prompt(
                f"ARM resource ID for {item}", hide_input=True
            ).strip()
        created = create_case_scope(
            case_id,
            resource_ids,
            approve_scope=_confirm_scope,
            expires_in_minutes=expires_in_minutes,
        )
    except (RuntimeError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    except (EOFError, KeyboardInterrupt) as exc:
        typer.echo("Scope setup cancelled; nothing was saved.", err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(
        f"scope_approved={len(created.targets)} target(s); expires={created.expires_at.isoformat()}"
    )


@app.command(name="investigate")
def investigate(
    case_id: str,
    goal: Annotated[
        str, typer.Option("--goal", help="Alias-only investigation request from Copilot.")
    ],
    rules_only: Annotated[bool, typer.Option("--rules-only")] = False,
) -> None:
    """Run one locally planned, operator-approved Azure read and evidence release."""

    if rules_only:
        typer.echo("Rules-only evidence scan: the local prose-model sweep is disabled.", err=True)
    try:
        turn = run_investigation_turn(
            case_id,
            goal,
            load_policy(),
            approve_query=_confirm_query,
            allow_rules_only=rules_only,
        )
    except (RuntimeError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    _report_investigation_turn(turn)


def _report_investigation_turn(turn: InvestigationTurn) -> None:
    if turn.status == "released" and turn.evidence_id is not None:
        typer.echo(f"evidence_id={turn.evidence_id}")
        typer.echo("Copilot may now read this evidence with Airlock's read_evidence MCP tool.")
        return
    messages = {
        "proposal_rejected": "Local planner rejected the request; no Azure query was run.",
        "query_denied": "Query approval was denied; no Azure query was run.",
        "result_not_released": "Result was blocked or not approved; no evidence was released.",
    }
    typer.echo(messages[turn.status], err=True)
    raise typer.Exit(code=2)


@app.command()
def restore(case_id: str, answer_file: Path) -> None:
    """Restore a saved Copilot answer locally using the case mapping."""

    rebuilt, unmapped = restore_case(case_id, answer_file.read_text(encoding="utf-8"))
    typer.echo(rebuilt)
    if unmapped:
        typer.echo(f"Unrestored references: {', '.join(unmapped)}", err=True)


if __name__ == "__main__":
    app()
