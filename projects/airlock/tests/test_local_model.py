"""Local prose sweep stays on loopback and locally locates exact model substrings."""

import json

import httpx
import pytest

from airlock.cases import prepare_case
from airlock.config import load_policy
from airlock.detect import model
from airlock.sanitize import sanitize
from airlock.vault import Vault


def test_local_model_url_rejects_remote_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIRLOCK_LOCAL_MODEL_URL", "https://models.example.com/v1/chat/completions")
    with pytest.raises(ValueError, match="loopback"):
        model.local_endpoint()


def test_lm_studio_uses_loopback_openai_compatible_api(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIRLOCK_LOCAL_MODEL_URL", "http://127.0.0.1:1234/v1/chat/completions")
    policy = load_policy().model_copy(deep=True)
    policy.model.provider = "lm_studio"
    policy.model.name = "qwen2.5-coder-7b-instruct"
    requests: list[dict[str, object]] = []

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        assert url == "http://127.0.0.1:1234/v1/chat/completions"
        assert kwargs["trust_env"] is False
        requests.append(kwargs["json"])
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '```json\n{"entities":[{"type":"PERSON","text":"Mira","score":0.9}]}\n```'}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    findings = model.detect_prose([(0, "Mira noticed repeated CPU spikes yesterday.")], policy, strict=True)
    assert [(item.entity_type, item.text) for item in findings] == [("PERSON", "Mira")]
    assert requests[0]["model"] == "qwen2.5-coder-7b-instruct"


def test_model_rejects_commentary_outside_fenced_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIRLOCK_LOCAL_MODEL_URL", "http://127.0.0.1:12345/v1/chat/completions")

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": 'Here is JSON:\n```json\n{"entities":[]}\n```'}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    with pytest.raises(RuntimeError, match="invalid structured output"):
        model.detect_prose([(0, "Mira noticed repeated CPU spikes yesterday.")], load_policy(), strict=True)


def test_local_model_retries_invalid_json_then_returns_valid_offset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AIRLOCK_LOCAL_MODEL_URL", "http://127.0.0.1:12345/v1/chat/completions")
    span = "Nexa Fabrics noticed repeated CPU spikes yesterday."
    calls: list[dict[str, object]] = []

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        assert url.startswith("http://127.0.0.1:")
        assert kwargs["trust_env"] is False
        calls.append(kwargs["json"])
        content = "bad JSON" if len(calls) == 1 else json.dumps(
            {"entities": [{"type": "ORG_NAME", "text": "Nexa Fabrics", "start": 0, "end": 12, "score": 0.94}]}
        )
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": content}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    findings = model.detect_prose([(30, span)], load_policy())
    assert len(calls) == 2
    assert [(finding.entity_type, finding.text, finding.start, finding.end) for finding in findings] == [
        ("ORG_NAME", "Nexa Fabrics", 30, 42)
    ]


def test_local_model_rejects_invented_offsets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIRLOCK_LOCAL_MODEL_URL", "http://localhost:12345/v1/chat/completions")
    attempts = 0

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"entities":[{"type":"PERSON","text":"Invented Person","start":0,"end":15,"score":0.9}]}'}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    assert model.detect_prose([(0, "The worker had a CPU spike during the incident.")], load_policy()) == []
    assert attempts == 2


def test_local_model_corrects_bad_offsets_when_text_is_exact(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIRLOCK_LOCAL_MODEL_URL", "http://127.0.0.1:12345/v1/chat/completions")
    source = "Mira from Meridian Logistics called Mira again."

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps({"entities": [
                {"type": "PERSON", "text": "Mira", "start": 99, "end": 101, "score": 0.9},
                {"type": "ORG_NAME", "text": "Meridian Logistics", "start": 8, "end": 20, "score": 0.8},
            ]})}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    found = model.detect_prose([(0, source)], load_policy(), strict=True)
    assert [(item.entity_type, item.start, item.end) for item in found] == [
        ("PERSON", 0, 4),
        ("PERSON", 36, 40),
        ("ORG_NAME", 10, 28),
    ]


def test_protected_case_rejects_unsupported_model_labels(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("AIRLOCK_LOCAL_MODEL_URL", "http://127.0.0.1:12345/v1/chat/completions")
    attempts = 0

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps({"entities": [
                {"type": "ORGANIZATION", "text": "Meridian Logistics", "start": 10, "end": 28, "score": 0.9}
            ]})}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    with pytest.raises(RuntimeError, match="invalid structured output"):
        prepare_case("Mira from Meridian Logistics reported a CPU spike.", load_policy(), tmp_path, decision=True)
    assert attempts == 2
    assert list(tmp_path.iterdir()) == []


def test_sanitizer_sends_json_prose_value_to_local_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("AIRLOCK_LOCAL_MODEL_URL", "http://127.0.0.1:12345/v1/chat/completions")
    source = '{"observation":"Nexa Fabrics saw CPU spikes during reporting."}'
    seen: list[str] = []

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        payload = kwargs["json"]
        span = payload["messages"][1]["content"].removeprefix("Text:\n")
        seen.append(span)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps({"entities": [
                {"type": "ORG_NAME", "text": "Nexa Fabrics", "start": 0, "end": 12, "score": 0.95}
            ]})}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    result = sanitize(source, load_policy(), Vault(b"local-model", tmp_path / "vault.json"))
    assert seen == ["Nexa Fabrics saw CPU spikes during reporting."]
    assert "Nexa Fabrics" not in result.text


def test_protected_case_aborts_when_local_model_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("AIRLOCK_LOCAL_MODEL_URL", "http://127.0.0.1:12345/v1/chat/completions")

    def failed_post(url: str, **kwargs: object) -> httpx.Response:
        raise httpx.ConnectError("offline", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", failed_post)
    with pytest.raises(RuntimeError, match="case was not released"):
        prepare_case("Mira from Meridian Logistics reported a billing delay.", load_policy(), tmp_path, decision=True)
    assert list(tmp_path.iterdir()) == []
