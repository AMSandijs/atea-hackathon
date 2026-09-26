"""The T21 investigation-loop evaluation runs offline and upholds the release invariants."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval import investigations


@pytest.fixture(scope="module")
def report(tmp_path_factory: pytest.TempPathFactory) -> dict:
    output = tmp_path_factory.mktemp("investigation-eval")
    return investigations.run_evaluation(output_dir=output, with_model=False)


def _turns(report: dict) -> list[dict]:
    return [turn for scenario in report["scenarios"] for turn in scenario["turns"]]


def test_scripted_run_covers_all_four_read_types_across_successive_turns(report: dict) -> None:
    operations = {turn["proposal"]["operation"] for turn in _turns(report) if turn["proposal"]}
    assert {"vm_cpu", "app_failures", "sql_metrics", "logic_runs"} <= operations
    assert any(len(scenario["turns"]) >= 4 for scenario in report["scenarios"])
    assert report["mode"] == "scripted"
    assert Path(report["output"]).is_file()
    assert json.loads(Path(report["output"]).read_text(encoding="utf-8"))["summary"]


def test_any_unexpected_outcome_fails_closed(report: dict) -> None:
    for turn in _turns(report):
        if turn["status"] not in turn["expected_status"]:
            assert turn["status"] in {"failed", "blocked", "denied", "proposal_rejected"}
            assert turn["useful"] is False


def _turn(report: dict, goal_prefix: str) -> dict:
    return next(turn for turn in _turns(report) if turn["goal"].startswith(goal_prefix))


def test_sql_metrics_read_is_released(report: dict) -> None:
    assert _turn(report, "Check SQL_1 CPU")["status"] == "released"


def test_app_failures_read_is_released(report: dict) -> None:
    assert _turn(report, "Check APP_1 failed requests")["status"] == "released"


def test_realistic_resource_names_are_not_blocked_as_secrets(report: dict) -> None:
    assert report["summary"]["naming"]["false_blocks"] == []


def test_case_text_hides_known_resource_names(report: dict) -> None:
    for scenario in report["scenarios"]:
        assert scenario["case_leaked"]["deterministic"] == []


def test_case_text_never_contains_secrets(report: dict) -> None:
    for scenario in report["scenarios"]:
        assert scenario["case_leaked"]["secret"] == []


def test_no_secret_or_deterministic_identifier_ever_reaches_copilot(report: dict) -> None:
    for turn in _turns(report):
        assert turn["leaked"]["secret"] == [], turn["goal"]
        assert turn["leaked"]["deterministic"] == [], turn["goal"]


def test_approvals_are_per_read_and_denials_run_no_read(report: dict) -> None:
    for turn in _turns(report):
        if turn["status"] == "released":
            assert turn["approvals"] == {"query": 1, "result": 1}, turn["goal"]
            assert turn["adapter_calls"] >= 1
        if turn["status"] == "proposal_rejected":
            assert turn["approvals"] == {"query": 0, "result": 0}
            assert turn["adapter_calls"] == 0
        if turn["status"] == "denied" and turn["approvals"]["result"] == 0:
            assert turn["adapter_calls"] == 0


def test_hard_cases_are_reported_not_hidden(report: dict) -> None:
    turns = _turns(report)
    assert any(turn["status"] == "blocked" for turn in turns)
    assert any(turn.get("injection_released") is True for turn in turns)
    summary = report["summary"]
    for key in ("turns", "status_match", "released", "useful", "leaked", "over_redacted", "naming"):
        assert key in summary
    assert set(summary["latency_ms"]) == {"plan", "supervise", "total"}


def test_evaluation_leaves_no_state_outside_its_temporary_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AIRLOCK_CASE_DIR", str(tmp_path / "must-stay-empty"))
    investigations.run_evaluation(output_dir=tmp_path / "out", with_model=False)
    assert not (tmp_path / "must-stay-empty").exists()
    import os

    assert os.environ["AIRLOCK_CASE_DIR"] == str(tmp_path / "must-stay-empty")
