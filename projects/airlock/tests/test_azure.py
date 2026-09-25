"""Azure capture is read-only and never exposes raw output to Copilot."""

import json
import subprocess

import pytest

from airlock.azure import capture_resource

RESOURCE_ID = (
    "/subscriptions/8f4c2b91-3d07-4a1e-b8c2-77e3a9d61f04/"
    "resourceGroups/nordbro-prd-rg/providers/Microsoft.Compute/virtualMachines/qconv-vm-prd"
)


def test_capture_resource_uses_only_az_resource_show(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        seen.extend(command)
        assert kwargs["capture_output"] is True
        return subprocess.CompletedProcess(command, 0, json.dumps({"id": RESOURCE_ID, "name": "qconv-vm-prd"}))

    monkeypatch.setattr("airlock.azure.shutil.which", lambda name: "C:/Azure/az.cmd")
    monkeypatch.setattr("airlock.azure.subprocess.run", fake_run)
    result = capture_resource(RESOURCE_ID)
    assert seen[1:3] == ["resource", "show"]
    assert "--ids" in seen
    assert "delete" not in seen
    assert json.loads(result)["name"] == "qconv-vm-prd"


def test_capture_resource_rejects_invalid_id_before_azure_call(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_which(name: str) -> None:
        raise AssertionError("Azure CLI must not be called")

    monkeypatch.setattr("airlock.azure.shutil.which", fail_which)
    with pytest.raises(ValueError, match="complete Azure resource ID"):
        capture_resource("nordbro-vm-prd & echo unsafe")


def test_capture_resource_can_include_read_only_cpu_metric(monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        payload = {"id": RESOURCE_ID} if len(commands) == 1 else {"value": [{"name": {"value": "Percentage CPU"}}]}
        return subprocess.CompletedProcess(command, 0, json.dumps(payload))

    monkeypatch.setattr("airlock.azure.shutil.which", lambda name: "C:/Azure/az.cmd")
    monkeypatch.setattr("airlock.azure.subprocess.run", fake_run)
    bundle = json.loads(capture_resource(RESOURCE_ID, metric="Percentage CPU"))
    assert commands[0][1:3] == ["resource", "show"]
    assert commands[1][1:4] == ["monitor", "metrics", "list"]
    assert commands[1][commands[1].index("--metric") + 1] == "Percentage CPU"
    assert bundle["metric"]["value"][0]["name"]["value"] == "Percentage CPU"


def test_capture_rejects_invalid_metric_before_azure_call(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_which(name: str) -> None:
        raise AssertionError("Azure CLI must not be called")

    monkeypatch.setattr("airlock.azure.shutil.which", fail_which)
    with pytest.raises(ValueError, match="metric name"):
        capture_resource(RESOURCE_ID, metric="CPU & echo unsafe")
