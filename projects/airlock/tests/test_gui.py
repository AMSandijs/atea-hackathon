"""Headless tests for the local approval bridge and GUI command."""

from __future__ import annotations

import threading

import pytest
from typer.testing import CliRunner

pytest.importorskip("tkinter")

from airlock.cli import app
from airlock.gui import ApprovalBridge


def _start_query_request(
    bridge: ApprovalBridge, queued: threading.Event, result: list[bool]
) -> threading.Thread:
    original_put = bridge._requests.put

    def notify_put(item: object, *args: object, **kwargs: object) -> None:
        original_put(item, *args, **kwargs)
        queued.set()

    bridge._requests.put = notify_put  # type: ignore[method-assign]
    worker = threading.Thread(target=lambda: result.append(bridge.approve_query(object())))
    worker.start()
    assert queued.wait(timeout=1)
    return worker


def test_approval_bridge_resolves_request_on_ui_caller_thread() -> None:
    bridge = ApprovalBridge(timeout_seconds=1)
    queued = threading.Event()
    result: list[bool] = []
    worker = _start_query_request(bridge, queued, result)
    ui_thread_id = threading.get_ident()
    reviewed: list[int] = []

    def approve(_request: object) -> bool:
        reviewed.append(threading.get_ident())
        return True

    assert bridge.drain(approve) == 1
    worker.join(timeout=1)

    assert not worker.is_alive()
    assert result == [True]
    assert reviewed == [ui_thread_id]


def test_approval_bridge_denies_review_errors_and_window_close() -> None:
    bridge = ApprovalBridge(timeout_seconds=1)
    queued = threading.Event()
    result: list[bool] = []
    worker = _start_query_request(bridge, queued, result)

    def fail(_request: object) -> bool:
        raise RuntimeError("UI failed")

    assert bridge.drain(fail) == 1
    worker.join(timeout=1)
    assert result == [False]

    queued = threading.Event()
    result = []
    worker = _start_query_request(bridge, queued, result)
    bridge.close()
    worker.join(timeout=1)
    assert not worker.is_alive()
    assert result == [False]


def test_window_close_denies_a_review_already_in_progress() -> None:
    bridge = ApprovalBridge(timeout_seconds=1)
    queued = threading.Event()
    result: list[bool] = []
    worker = _start_query_request(bridge, queued, result)
    review_started = threading.Event()
    finish_review = threading.Event()

    def delayed_review(_request: object) -> bool:
        review_started.set()
        assert finish_review.wait(timeout=1)
        return True

    reviewer = threading.Thread(target=lambda: bridge.drain(delayed_review))
    reviewer.start()
    assert review_started.wait(timeout=1)
    bridge.close()
    worker.join(timeout=1)
    assert result == [False]

    finish_review.set()
    reviewer.join(timeout=1)
    assert not reviewer.is_alive()
    assert result == [False]


def test_approval_bridge_timeout_cannot_be_overridden_by_late_approval() -> None:
    bridge = ApprovalBridge(timeout_seconds=0.05)
    queued = threading.Event()
    result: list[bool] = []
    worker = _start_query_request(bridge, queued, result)
    review_started = threading.Event()
    finish_review = threading.Event()

    def delayed_review(_request: object) -> bool:
        review_started.set()
        assert finish_review.wait(timeout=1)
        return True

    reviewer = threading.Thread(target=lambda: bridge.drain(delayed_review))
    reviewer.start()
    assert review_started.wait(timeout=1)
    worker.join(timeout=1)
    assert result == [False]

    finish_review.set()
    reviewer.join(timeout=1)
    assert not reviewer.is_alive()
    assert result == [False]


def test_gui_command_dispatches_to_desktop_launcher(monkeypatch: pytest.MonkeyPatch) -> None:
    from airlock import gui

    launched: list[bool] = []
    monkeypatch.setattr(gui, "launch_gui", lambda: launched.append(True))

    result = CliRunner().invoke(app, ["gui"])

    assert result.exit_code == 0, result.output
    assert launched == [True]
