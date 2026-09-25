"""Command-line entry point for the Airlock build."""

import json
import os
import secrets
import time
from pathlib import Path
from typing import Annotated

import typer

from .azure import capture_resource
from .cases import prepare_case, restore_case
from .checkpoint import checkpoint
from .config import load_policy
from .detect.model import local_endpoint
from .gateway import send
from .models import AirlockResult
from .rehydrate import rehydrate
from .sanitize import sanitize
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


@app.command()
def restore(case_id: str, answer_file: Path) -> None:
    """Restore a saved Copilot answer locally using the case mapping."""

    rebuilt, unmapped = restore_case(case_id, answer_file.read_text(encoding="utf-8"))
    typer.echo(rebuilt)
    if unmapped:
        typer.echo(f"Unrestored references: {', '.join(unmapped)}", err=True)


if __name__ == "__main__":
    app()
