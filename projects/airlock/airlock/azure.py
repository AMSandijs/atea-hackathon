"""Read-only local Azure collection using the operator's Azure CLI identity."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from .scope import ScopeError, _operations_for_resource_id

if TYPE_CHECKING:
    from .broker import AuthorizedRead

_RESOURCE_ID = re.compile(
    r"/subscriptions/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}/resourceGroups/[A-Za-z0-9._-]+/"
    r"providers/[A-Za-z0-9.]+(?:/[A-Za-z0-9._-]+){2,}\Z",
    re.IGNORECASE,
)
_METRIC_NAME = re.compile(r"[A-Za-z][A-Za-z0-9 ._/-]{0,79}\Z")
_MAX_AZURE_OUTPUT_BYTES = 1_048_576
_MAX_LOGIC_RUNS = 100
_METRIC_READS = {
    "vm_cpu": ((("Percentage CPU",), ("Average", "Maximum")),),
    "app_failures": ((("requests/failed", "exceptions/count"), ("Count",)),),
    "sql_metrics": (
        (
            ("cpu_percent", "physical_data_read_percent", "log_write_percent"),
            ("Average", "Maximum"),
        ),
        (("deadlock",), ("Total",)),
    ),
}


class AzureReadError(RuntimeError):
    """A fixed Azure read failed without exposing CLI output."""


def _read_json(
    command: list[str], runner: Callable[..., subprocess.CompletedProcess[str]] | None = None
) -> object:
    try:
        completed = (runner or subprocess.run)(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=90,
            shell=False,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("Azure read failed; check local sign-in and Reader access") from exc
    if (
        not isinstance(completed.stdout, str)
        or len(completed.stdout.encode("utf-8", errors="replace")) > _MAX_AZURE_OUTPUT_BYTES
    ):
        raise RuntimeError("Azure response exceeded the local read limit")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Azure returned invalid JSON") from exc


def capture_resource(resource_id: str, metric: str | None = None) -> str:
    """Read a resource and optional metric into one local bundle for sanitization."""

    if not _RESOURCE_ID.fullmatch(resource_id):
        raise ValueError("expected a complete Azure resource ID")
    if metric is not None and not _METRIC_NAME.fullmatch(metric):
        raise ValueError("invalid Azure metric name")
    executable = shutil.which("az")
    if executable is None:
        raise RuntimeError("Azure CLI is not installed or on PATH")
    resource = _read_json(
        [
            executable,
            "resource",
            "show",
            "--ids",
            resource_id,
            "--output",
            "json",
            "--only-show-errors",
        ]
    )
    if not isinstance(resource, dict):
        raise TypeError("Azure returned an unexpected response")
    if metric is None:
        return json.dumps(resource, indent=2, sort_keys=True)
    measurements = _read_json(
        [
            executable,
            "monitor",
            "metrics",
            "list",
            "--resource",
            resource_id,
            "--metric",
            metric,
            "--offset",
            "1h",
            "--interval",
            "PT1M",
            "--aggregation",
            "Average",
            "Maximum",
            "--output",
            "json",
            "--only-show-errors",
        ]
    )
    if not isinstance(measurements, dict):
        raise TypeError("Azure returned an unexpected metric response")
    return json.dumps({"resource": resource, "metric": measurements}, indent=2, sort_keys=True)


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _logic_run_projection(payload: object, start: datetime, end: datetime) -> dict[str, object]:
    if not isinstance(payload, dict) or not isinstance(payload.get("value"), list):
        raise AzureReadError("Azure returned an unexpected Logic App response")
    rows: list[dict[str, object]] = []
    for run in payload["value"][:_MAX_LOGIC_RUNS]:
        properties = run.get("properties") if isinstance(run, dict) else None
        if not isinstance(properties, dict):
            continue
        started = _timestamp(properties.get("startTime"))
        if started is None or not start <= started <= end:
            continue
        row: dict[str, object] = {
            key: properties[key]
            for key in ("startTime", "endTime", "status", "code")
            if isinstance(properties.get(key), str)
        }
        error = properties.get("error")
        if isinstance(error, dict):
            row["error"] = {
                key: value[:2_000]
                for key, value in error.items()
                if key in {"code", "message"} and isinstance(value, str)
            }
        elif isinstance(error, str):
            row["error"] = error[:2_000]
        rows.append(row)
    return {"runs": rows, "page_limit": _MAX_LOGIC_RUNS}


def _execute_authorized_read(
    authorized: AuthorizedRead,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> str:
    """Execute only a broker-produced read capability; output remains local and raw."""

    from .broker import AuthorizedRead

    if not isinstance(authorized, AuthorizedRead):
        raise AzureReadError("query authorization is invalid")
    if (
        type(authorized.time_range_minutes) is not int
        or not 1 <= authorized.time_range_minutes <= 1_440
    ):
        raise AzureReadError("query time range is invalid")
    try:
        allowed = _operations_for_resource_id(authorized.resource_id)
    except (ScopeError, TypeError) as exc:
        raise AzureReadError("query target is invalid") from exc
    if authorized.operation not in allowed:
        raise AzureReadError("query operation is not allowed for its target")
    executable = shutil.which("az")
    if executable is None:
        raise AzureReadError("Azure CLI is not installed or on PATH")

    end = datetime.now(UTC)
    start = end - timedelta(minutes=authorized.time_range_minutes)
    start_text = start.isoformat(timespec="seconds")
    end_text = end.isoformat(timespec="seconds")
    try:
        if authorized.operation == "logic_runs":
            command = [
                executable,
                "rest",
                "--method",
                "get",
                "--url",
                f"{authorized.resource_id}/runs?api-version=2019-05-01",
                "--url-parameters",
                f"$top={_MAX_LOGIC_RUNS}",
                f"$filter=StartTime ge '{start_text}'",
                "--output",
                "json",
                "--only-show-errors",
            ]
            payload = _read_json(command, runner)
            result: object = _logic_run_projection(payload, start, end)
        elif authorized.operation in _METRIC_READS:
            reads = _METRIC_READS[authorized.operation]
            metric_results: list[object] = []
            for metric_names, aggregations in reads:
                command = [
                    executable,
                    "monitor",
                    "metrics",
                    "list",
                    "--resource",
                    authorized.resource_id,
                    "--metrics",
                    *metric_names,
                    "--start-time",
                    start_text,
                    "--end-time",
                    end_text,
                    "--interval",
                    "1m",
                    "--aggregation",
                    *aggregations,
                    "--output",
                    "json",
                    "--only-show-errors",
                ]
                payload = _read_json(command, runner)
                if not isinstance(payload, dict):
                    raise AzureReadError("Azure returned an unexpected metrics response")
                metric_results.append(payload)
            result = {"queries": metric_results}
        else:
            raise AzureReadError("query operation is not supported")
    except AzureReadError:
        raise
    except RuntimeError as exc:
        raise AzureReadError("Azure read failed; no result was released") from exc

    document = json.dumps(
        {
            "operation": authorized.operation,
            "target_alias": authorized.target_alias,
            "window": {"start": start_text, "end": end_text},
            "result": result,
        },
        indent=2,
        sort_keys=True,
    )
    if len(document.encode("utf-8")) > _MAX_AZURE_OUTPUT_BYTES:
        raise AzureReadError("Azure response exceeded the local read limit")
    return document
