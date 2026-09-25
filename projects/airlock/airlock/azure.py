"""Read-only local Azure collection using the operator's Azure CLI identity."""

from __future__ import annotations

import json
import re
import shutil
import subprocess

_RESOURCE_ID = re.compile(
    r"/subscriptions/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}/resourceGroups/[A-Za-z0-9._-]+/"
    r"providers/[A-Za-z0-9.]+(?:/[A-Za-z0-9._-]+){2,}\Z",
    re.IGNORECASE,
)
_METRIC_NAME = re.compile(r"[A-Za-z][A-Za-z0-9 ._/-]{0,79}\Z")


def _read_json(command: list[str]) -> object:
    try:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=90,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("Azure read failed; check local sign-in and Reader access") from exc
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
        [executable, "resource", "show", "--ids", resource_id, "--output", "json", "--only-show-errors"]
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
