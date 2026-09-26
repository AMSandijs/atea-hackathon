"""Explicitly approved, local cases for the Copilot investigation workflow."""

from __future__ import annotations

import json
import os
import re
import secrets
from pathlib import Path

from .checkpoint import checkpoint
from .config import Policy
from .detect.model import local_endpoint
from .rehydrate import rehydrate
from .sanitize import sanitize
from .vault import Vault

_CASE_ID = re.compile(r"[0-9a-f]{24}\Z")
_MAX_SOURCE_BYTES = 2 * 1024 * 1024
_MAX_EVIDENCE_BYTES = 1024 * 1024


def case_directory() -> Path:
    """Return the private local case directory."""

    configured = os.environ.get("AIRLOCK_CASE_DIR")
    return Path(configured) if configured else Path.home() / ".airlock" / "cases"


def _paths(case_id: str, directory: Path) -> tuple[Path, Path]:
    if not _CASE_ID.fullmatch(case_id):
        raise ValueError("invalid case ID")
    return directory / f"{case_id}.json", directory / f"{case_id}.map.json"


def _evidence_paths(case_id: str, evidence_id: str, directory: Path) -> tuple[Path, Path]:
    if not _CASE_ID.fullmatch(case_id) or not _CASE_ID.fullmatch(evidence_id):
        raise ValueError("invalid case or evidence ID")
    prefix = f"{case_id}.evidence-{evidence_id}"
    return directory / f"{prefix}.json", directory / f"{prefix}.map.json"


def _read_mapping(path: Path) -> dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    mapping = data.get("mapping")
    if not isinstance(mapping, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in mapping.items()
    ):
        raise ValueError("case mapping is invalid")
    return mapping


def _write_private(path: Path, data: dict[str, object]) -> None:
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(data, sort_keys=True, indent=2) + "\n")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def prepare_case(
    source: str,
    policy: Policy,
    directory: Path | None = None,
    decision: bool | None = None,
    allow_rules_only: bool = False,
) -> str | None:
    """Approve a sanitized snapshot and return an opaque case ID.

    Rejected or blocked snapshots are never persisted for MCP to read.
    """

    if len(source.encode("utf-8")) > _MAX_SOURCE_BYTES:
        raise ValueError("snapshot exceeds the 2 MB case limit")
    model_ready = local_endpoint() is not None
    if not model_ready and not allow_rules_only:
        raise ValueError(
            "local model is not configured; set AIRLOCK_LOCAL_MODEL_URL or opt into rules-only mode"
        )
    root = directory or case_directory()
    case_id = secrets.token_hex(12)
    public_path, map_path = _paths(case_id, root)
    vault = Vault(secrets.token_bytes(32), root / f"{case_id}.unused")
    sanitized = sanitize(source, policy, vault, strict_model=model_ready)
    if not checkpoint(source, sanitized, policy, decision=decision):
        return None
    root.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(root, 0o700)
    except OSError:
        pass
    _write_private(map_path, {"mapping": sanitized.mapping})
    try:
        _write_private(
            public_path,
            {
                "case_id": case_id,
                "approved": True,
                "text": sanitized.text,
                "mode": "local_model" if model_ready else "rules_only",
            },
        )
    except Exception:
        map_path.unlink(missing_ok=True)
        raise
    return case_id


def read_case(case_id: str, directory: Path | None = None) -> str:
    """Return only the approved sanitized text for an opaque case ID."""

    public_path, _ = _paths(case_id, directory or case_directory())
    data = json.loads(public_path.read_text(encoding="utf-8"))
    if data.get("approved") is not True or data.get("case_id") != case_id:
        raise ValueError("case is not approved")
    text = data.get("text")
    if not isinstance(text, str):
        raise TypeError("case text is invalid")
    return text


def release_evidence(
    case_id: str,
    raw_result: str,
    policy: Policy,
    *,
    decision: bool | None = None,
    allow_rules_only: bool = False,
    directory: Path | None = None,
) -> str | None:
    """Sanitize and separately approve one Azure result before local persistence."""

    if not isinstance(raw_result, str) or len(raw_result.encode("utf-8")) > _MAX_EVIDENCE_BYTES:
        raise ValueError("Azure result exceeds the 1 MB evidence limit or is not text")
    root = directory or case_directory()
    read_case(case_id, root)
    _, case_map_path = _paths(case_id, root)
    case_mapping = _read_mapping(case_map_path)
    model_ready = local_endpoint() is not None
    if not model_ready and not allow_rules_only:
        raise ValueError(
            "local model is not configured; set AIRLOCK_LOCAL_MODEL_URL or opt into rules-only mode"
        )

    evidence_id = secrets.token_hex(12)
    evidence_path, evidence_map_path = _evidence_paths(case_id, evidence_id, root)
    vault = Vault(
        secrets.token_bytes(32),
        root / f"{case_id}.evidence-{evidence_id}.unused",
        initial_pairs=case_mapping,
    )
    sanitized = sanitize(raw_result, policy, vault, strict_model=model_ready)
    if not checkpoint(raw_result, sanitized, policy, decision=decision):
        return None

    root.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(root, 0o700)
    except OSError:
        pass
    _write_private(evidence_map_path, {"mapping": vault.pairs()})
    try:
        _write_private(
            evidence_path,
            {
                "case_id": case_id,
                "evidence_id": evidence_id,
                "approved": True,
                "text": sanitized.text,
                "mode": "local_model" if model_ready else "rules_only",
            },
        )
    except Exception:
        evidence_map_path.unlink(missing_ok=True)
        raise
    return evidence_id


def read_evidence(case_id: str, evidence_id: str, directory: Path | None = None) -> str:
    """Return only approved sanitized evidence attached to an approved case."""

    root = directory or case_directory()
    read_case(case_id, root)
    evidence_path, _ = _evidence_paths(case_id, evidence_id, root)
    data = json.loads(evidence_path.read_text(encoding="utf-8"))
    if (
        data.get("approved") is not True
        or data.get("case_id") != case_id
        or data.get("evidence_id") != evidence_id
    ):
        raise ValueError("evidence is not approved for this case")
    text = data.get("text")
    if not isinstance(text, str) or len(text.encode("utf-8")) > _MAX_EVIDENCE_BYTES:
        raise ValueError("evidence text is invalid")
    return text


def restore_case(
    case_id: str,
    answer: str,
    directory: Path | None = None,
) -> tuple[str, list[str]]:
    """Restore a saved Copilot answer locally using this case's reverse map."""

    root = directory or case_directory()
    read_case(case_id, root)
    _, map_path = _paths(case_id, root)
    mapping = _read_mapping(map_path)
    sidecar_pattern = re.compile(re.escape(case_id) + r"\.evidence-([0-9a-f]{24})\.map\.json\Z")
    for sidecar in root.glob(f"{case_id}.evidence-*.map.json"):
        match = sidecar_pattern.fullmatch(sidecar.name)
        if match is None:
            continue
        evidence_id = match.group(1)
        try:
            read_evidence(case_id, evidence_id, root)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
        for stand_in, original in _read_mapping(sidecar).items():
            existing = mapping.get(stand_in)
            if existing is not None and existing != original:
                raise ValueError("evidence mapping collides with case mapping")
            mapping[stand_in] = original
    return rehydrate(answer, mapping)
