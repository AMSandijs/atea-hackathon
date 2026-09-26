"""The local planner returns bounded proposals and has no Azure execution path."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from airlock.config import load_policy
from airlock.planner import PlannerError, plan_query, validate_proposal

CAPABILITIES = {
    "VM_1": ["vm_cpu"],
    "APP_1": ["app_failures"],
    "LOGIC_1": ["logic_runs"],
}


def _proposal(operation: str = "vm_cpu", target: str = "VM_1", minutes: int = 30) -> str:
    return json.dumps(
        {"operation": operation, "target_alias": target, "time_range_minutes": minutes}
    )


def test_plan_query_sends_only_capabilities_to_loopback_model(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        seen["url"] = url
        seen.update(kwargs)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": _proposal()}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr("airlock.planner.local_endpoint", lambda: "http://127.0.0.1:1234/v1/chat/completions")
    monkeypatch.setattr("airlock.planner.httpx.post", fake_post)
    result = plan_query("Check CPU for VM_1 in the last 30 minutes", CAPABILITIES, load_policy())

    assert (result.operation, result.target_alias, result.time_range_minutes) == ("vm_cpu", "VM_1", 30)
    assert seen["url"].startswith("http://127.0.0.1:")
    assert seen["trust_env"] is False
    payload = seen["json"]
    assert payload["response_format"]["type"] == "json_schema"
    schema = payload["response_format"]["json_schema"]["schema"]
    assert schema["properties"]["target_alias"]["enum"] == ["APP_1", "LOGIC_1", "VM_1", "NONE"]
    message = json.loads(payload["messages"][1]["content"])
    assert message["capabilities"] == CAPABILITIES
    assert "real" not in message["goal"]


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        (_proposal("vm_cpu", "VM_999"), "outside the approved case scope"),
        (_proposal("logic_runs", "VM_1"), "not allowed for this case target"),
        (_proposal("vm_cpu", "VM_1", 1_441), "invalid query proposal"),
        ('{"operation":"vm_cpu","target_alias":"VM_1","time_range_minutes":30,"command":"az vm delete"}', "invalid query proposal"),
        ('```json\n{"operation":"vm_cpu","target_alias":"VM_1","time_range_minutes":30}\n```', "invalid query proposal"),
    ],
)
def test_validate_proposal_rejects_untrusted_or_invalid_model_output(raw: str, message: str) -> None:
    with pytest.raises(PlannerError, match=message):
        validate_proposal(raw, CAPABILITIES)


def test_reject_proposal_has_no_target() -> None:
    result = validate_proposal(_proposal("reject", "NONE"), CAPABILITIES)
    assert result.operation == "reject"

    with pytest.raises(PlannerError, match="must not name a target"):
        validate_proposal(_proposal("reject", "VM_1"), CAPABILITIES)


def test_plan_query_fails_closed_without_local_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("airlock.planner.local_endpoint", lambda: None)
    with pytest.raises(PlannerError, match="not configured"):
        plan_query("Check CPU for VM_1", CAPABILITIES, load_policy())


def test_plan_query_rejects_unknown_alias_before_model_call(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_endpoint() -> str:
        raise AssertionError("out-of-scope alias must fail before contacting the model")

    monkeypatch.setattr("airlock.planner.local_endpoint", fail_endpoint)
    with pytest.raises(PlannerError, match="outside the approved case scope"):
        plan_query("Check CPU for VM_999", CAPABILITIES, load_policy())


def test_plan_query_requires_one_explicit_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_endpoint() -> str:
        raise AssertionError("ambiguous alias request must fail before contacting the model")

    monkeypatch.setattr("airlock.planner.local_endpoint", fail_endpoint)
    with pytest.raises(PlannerError, match="exactly one approved target alias"):
        plan_query("Compare VM_1 and APP_1", CAPABILITIES, load_policy())


def test_plan_query_rejects_model_target_change(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": _proposal("app_failures", "APP_1")}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr("airlock.planner.local_endpoint", lambda: "http://127.0.0.1:1234/v1/chat/completions")
    monkeypatch.setattr("airlock.planner.httpx.post", fake_post)
    with pytest.raises(PlannerError, match="changed the requested target alias"):
        plan_query("Check CPU for VM_1", CAPABILITIES, load_policy())


def test_plan_query_rejects_invalid_capabilities_before_model_call(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_endpoint() -> str:
        raise AssertionError("invalid capabilities must fail before contacting the model")

    monkeypatch.setattr("airlock.planner.local_endpoint", fail_endpoint)
    with pytest.raises(PlannerError, match="capabilities are invalid"):
        plan_query("Check CPU", {"VM_1": ["az vm delete"]}, load_policy())


def test_plan_query_hides_transport_error_details(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_post(url: str, **kwargs: Any) -> httpx.Response:
        raise httpx.ConnectError("contains request details", request=httpx.Request("POST", url))

    monkeypatch.setattr("airlock.planner.local_endpoint", lambda: "http://127.0.0.1:1234/v1/chat/completions")
    monkeypatch.setattr("airlock.planner.httpx.post", fail_post)
    with pytest.raises(PlannerError, match="no Azure query was issued") as error:
        plan_query("Check CPU for VM_1", CAPABILITIES, load_policy())
    assert "request details" not in str(error.value)


def _model_reply(monkeypatch: pytest.MonkeyPatch, minutes: int, seen: dict | None = None) -> None:
    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        if seen is not None:
            seen.update(kwargs)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": _proposal(minutes=minutes)}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(
        "airlock.planner.local_endpoint", lambda: "http://127.0.0.1:1234/v1/chat/completions"
    )
    monkeypatch.setattr("airlock.planner.httpx.post", fake_post)


@pytest.mark.parametrize(
    ("goal", "minutes"),
    [
        ("Check VM_1 CPU over the last 2 hours", 120),
        ("Check VM_1 CPU for the last hour", 60),
        ("Check VM_1 CPU for 45 minutes", 45),
        ("Check VM_1 CPU for the last day", 1440),
    ],
)
def test_explicit_duration_must_match_the_proposal(
    monkeypatch: pytest.MonkeyPatch, goal: str, minutes: int
) -> None:
    _model_reply(monkeypatch, minutes)
    assert plan_query(goal, CAPABILITIES, load_policy()).time_range_minutes == minutes
    _model_reply(monkeypatch, 168)
    with pytest.raises(PlannerError):
        plan_query(goal, CAPABILITIES, load_policy())


def test_explicit_duration_above_limit_is_rejected_before_the_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "airlock.planner.local_endpoint", lambda: "http://127.0.0.1:1234/v1/chat/completions"
    )
    monkeypatch.setattr(
        "airlock.planner.httpx.post", lambda *_a, **_k: pytest.fail("model must not be called")
    )
    with pytest.raises(PlannerError):
        plan_query("Show VM_1 CPU for the last 3 days", CAPABILITIES, load_policy())


def test_prompt_sets_a_default_window_when_none_is_given(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict = {}
    _model_reply(monkeypatch, 60, seen)
    plan_query("Check VM_1 CPU", CAPABILITIES, load_policy())
    assert "60 minutes" in seen["json"]["messages"][0]["content"]
