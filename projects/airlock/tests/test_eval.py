from pathlib import Path

import pytest

from airlock.config import load_policy
from airlock.models import Finding
from eval.score import evaluate_corpus


def test_corpus_eval_writes_metrics_and_misses(tmp_path: Path) -> None:
    project = Path(__file__).parents[1]
    result = evaluate_corpus(
        corpus_dir=project / "eval" / "corpus",
        seeds_path=project / "eval" / "seeds.yaml",
        output_dir=tmp_path,
    )
    assert result["recall"]["total"] > 0
    assert 0 <= result["recall"]["value"] <= 1
    assert 0 <= result["precision"]["value"] <= 1
    assert Path(result["output"]).exists()
    assert "per_entity_type" in result["recall"]


def test_model_eval_reports_incremental_prose_recall(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from airlock.detect import model

    monkeypatch.setenv("AIRLOCK_LOCAL_MODEL_URL", "http://127.0.0.1:12345/v1/chat/completions")

    def fake_detect(spans: list[tuple[int, str]], policy: object, strict: bool = False) -> list[Finding]:
        del policy, strict
        findings: list[Finding] = []
        for base, span in spans:
            for entity_type, value in (("PERSON", "Mira"), ("ORG_NAME", "Meridian Logistics")):
                position = span.find(value)
                if position >= 0:
                    findings.append(Finding(entity_type, value, base + position, base + position + len(value), "model", 0.9))
        return findings

    monkeypatch.setattr(model, "detect_prose", fake_detect)
    result = evaluate_corpus(output_dir=tmp_path, with_model=True)
    assert result["mode"] == "local_model"
    assert result["recall"]["found"] == result["recall"]["total"]
    assert result["model"] == {"provider": "lm_studio", "name": "qwen2.5-coder-7b-instruct"}
    comparison_policy = load_policy()
    comparison_policy.model.name = "qwen2.5-coder-14b-instruct"
    comparison = evaluate_corpus(output_dir=tmp_path, policy=comparison_policy, with_model=True)
    assert result["output"] != comparison["output"]
    assert Path(result["output"]).exists() and Path(comparison["output"]).exists()
