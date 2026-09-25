"""Corpus scoring for deterministic Airlock detector regressions."""

from __future__ import annotations

import json
import re
import statistics
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from airlock.classify import classify
from airlock.config import Policy, load_policy
from airlock.detect import entropy, model, rules
from airlock.detect.model import LocalModelError
from airlock.models import Finding
from airlock.sanitize import _prose_spans


@dataclass(frozen=True)
class Seed:
    file: str
    entity_type: str
    text: str
    offset: int
    must_detect: bool


def load_seeds(path: Path, corpus_dir: Path) -> list[Seed]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    seeds: list[Seed] = []
    for item in raw:
        source = corpus_dir / item["file"]
        text = str(item["text"])
        offset = int(item.get("offset", source.read_text(encoding="utf-8").find(text)))
        seeds.append(Seed(item["file"], item["entity_type"], text, offset, bool(item["must_detect"])))
    return seeds


def _match(seed: Seed, finding: Finding) -> bool:
    return seed.entity_type == finding.entity_type and seed.text == finding.text


def evaluate_corpus(
    corpus_dir: Path | None = None,
    seeds_path: Path | None = None,
    output_dir: Path | None = None,
    policy: Policy | None = None,
    with_model: bool = False,
) -> dict[str, Any]:
    """Score the rules and entropy detectors and write a dated JSON result."""

    project_root = Path(__file__).parents[1]
    corpus = corpus_dir or project_root / "eval" / "corpus"
    seeds_file = seeds_path or project_root / "eval" / "seeds.yaml"
    destination = output_dir or project_root / "eval"
    active_policy = policy or load_policy(project_root / "policy.yaml")
    if with_model and model.local_endpoint() is None:
        raise ValueError("AIRLOCK_LOCAL_MODEL_URL is required for model evaluation")
    seeds = load_seeds(seeds_file, corpus)
    positive_seeds = [seed for seed in seeds if seed.must_detect]
    findings_by_file: dict[str, list[Finding]] = {}
    stage_times: dict[str, list[float]] = {"rules": [], "entropy": [], "model": [], "vault": [], "rehydrate": []}
    for path in sorted(corpus.iterdir()):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        started = time.perf_counter()
        detected = rules.detect(text, active_policy)
        stage_times["rules"].append((time.perf_counter() - started) * 1000)
        started = time.perf_counter()
        detected.extend(entropy.detect(text, active_policy))
        stage_times["entropy"].append((time.perf_counter() - started) * 1000)
        if with_model:
            spans = _prose_spans(text, detected)
            if any(model._looks_like_prose(span) for _, span in spans):
                started = time.perf_counter()
                try:
                    detected.extend(model.detect_prose(spans, active_policy, strict=True))
                except LocalModelError as exc:
                    raise LocalModelError(f"model evaluation failed in {path.name}: {exc}") from exc
                stage_times["model"].append((time.perf_counter() - started) * 1000)
        findings_by_file[path.name] = classify(detected, active_policy)
    matched_seed_indexes: set[int] = set()
    matched_findings: set[tuple[str, int]] = set()
    for seed_index, seed in enumerate(positive_seeds):
        for finding_index, finding in enumerate(findings_by_file.get(seed.file, [])):
            if _match(seed, finding):
                matched_seed_indexes.add(seed_index)
                matched_findings.add((seed.file, finding_index))
                break
    misses = [asdict(seed) for index, seed in enumerate(positive_seeds) if index not in matched_seed_indexes]
    false_positives: list[dict[str, Any]] = []
    for filename, findings in findings_by_file.items():
        for index, finding in enumerate(findings):
            if (filename, index) not in matched_findings:
                false_positives.append(
                    {
                        "file": filename,
                        "entity_type": finding.entity_type,
                        "text": finding.text,
                        "offset": finding.start,
                    }
                )
    per_type: dict[str, dict[str, float | int]] = {}
    for entity_type in sorted({seed.entity_type for seed in positive_seeds}):
        typed = [seed for seed in positive_seeds if seed.entity_type == entity_type]
        hit_count = sum(1 for seed in typed if seed in [positive_seeds[index] for index in matched_seed_indexes])
        per_type[entity_type] = {"found": hit_count, "total": len(typed), "recall": hit_count / len(typed)}
    total_findings = sum(len(findings) for findings in findings_by_file.values())
    result: dict[str, Any] = {
        "date": datetime.now(UTC).date().isoformat(),
        "mode": "local_model" if with_model else "rules_only",
        "model": {"provider": active_policy.model.provider, "name": active_policy.model.name} if with_model else None,
        "corpus_files": len(findings_by_file),
        "recall": {
            "found": len(matched_seed_indexes),
            "total": len(positive_seeds),
            "value": len(matched_seed_indexes) / len(positive_seeds) if positive_seeds else 1.0,
            "misses": misses,
            "per_entity_type": per_type,
        },
        "precision": {
            "true_findings": len(matched_findings),
            "total_findings": total_findings,
            "value": len(matched_findings) / total_findings if total_findings else 1.0,
            "false_positives": false_positives,
        },
        "quality": {"status": "not_run", "equivalent": None, "total": 0},
        "latency_ms": {
            stage: {"median": statistics.median(values) if values else 0.0, "worst": max(values) if values else 0.0}
            for stage, values in stage_times.items()
        },
    }
    destination.mkdir(parents=True, exist_ok=True)
    suffix = ""
    if with_model:
        slug = re.sub(r"[^a-z0-9]+", "-", f"{active_policy.model.provider}-{active_policy.model.name}".lower()).strip("-")
        suffix = f"-{slug[:100]}"
    output_path = destination / f"results-{datetime.now(UTC).date().isoformat()}{suffix}.json"
    output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result["output"] = str(output_path)
    return result


def print_summary(result: dict[str, Any]) -> None:
    recall = result["recall"]
    precision = result["precision"]
    print(f"recall     {recall['value']:.0%} ({recall['found']}/{recall['total']})")
    for entity_type, counts in recall["per_entity_type"].items():
        print(f"  {entity_type}: {counts['found']}/{counts['total']}")
    print(f"precision  {precision['value']:.0%} ({precision['true_findings']}/{precision['total_findings']})")
    print("quality    not run")
    print(f"latency    rules median {result['latency_ms']['rules']['median']:.1f} ms")
    if result["mode"] == "local_model":
        model_latency = result["latency_ms"]["model"]
        print(f"           model per eligible file median {model_latency['median'] / 1000:.1f} s, worst {model_latency['worst'] / 1000:.1f} s")
    if recall["misses"]:
        print(f"misses     {len(recall['misses'])}")
        for miss in recall["misses"]:
            print(f"  {miss['file']}:{miss['offset']} {miss['entity_type']} {miss['text']}")
