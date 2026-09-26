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


@pytest.fixture(scope="module")
def tk_root():
    """One Tcl interpreter per module; repeated tk.Tk() is unreliable on Windows."""

    import tkinter as tk

    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"no display available for Tk: {exc}")
    root.withdraw()
    yield root
    root.destroy()


def _desktop(tk_root, tmp_path, monkeypatch: pytest.MonkeyPatch):
    import tkinter as tk

    from airlock import gui

    monkeypatch.setenv("AIRLOCK_CASE_DIR", str(tmp_path))
    window = tk.Toplevel(tk_root)
    window.withdraw()
    return gui, gui.AirlockDesktop(window)


def _pump(desktop, until, timeout: float = 5.0) -> None:
    import time

    deadline = time.monotonic() + timeout
    while not until() and time.monotonic() < deadline:
        desktop.root.update()
        time.sleep(0.01)


def test_gui_claims_copilot_request_for_loaded_case_and_runs_one_supervised_turn(
    tk_root, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from airlock.handoff import enqueue_request, request_status
    from airlock.planner import QueryProposal

    gui, desktop = _desktop(tk_root, tmp_path, monkeypatch)
    case_id, other_case = "a" * 24, "b" * 24
    proposal = QueryProposal(operation="vm_cpu", target_alias="VM_1", time_range_minutes=30)
    ran: list[tuple[str, str]] = []

    def fake_run(supervisor, record, _policy, *, approve_query, approve_result, **_kwargs):
        ran.append((record.case_id, record.request_id))
        assert approve_query == desktop.bridge.approve_query
        assert approve_result == desktop.bridge.approve_result
        supervisor.transition(record.request_id, "awaiting_query_approval")
        supervisor.transition(record.request_id, "denied")
        return "denied"

    monkeypatch.setattr(gui, "run_queued_request", fake_run)
    try:
        _, other_id = enqueue_request(
            other_case, proposal, claim_seconds=300, deadline_minutes=30, directory=tmp_path
        )
        _, request_id = enqueue_request(
            case_id, proposal, claim_seconds=300, deadline_minutes=30, directory=tmp_path
        )
        desktop._check_copilot_requests()
        assert ran == []  # no case loaded: nothing is claimed

        desktop._loaded_case_id = case_id
        desktop._active_aliases = ()
        desktop._check_copilot_requests()
        assert ran == []  # case loaded without an approved scope: nothing is claimed
        assert request_status(case_id, request_id, tmp_path) == {"status": "queued"}

        desktop._active_aliases = ("VM_1",)
        desktop._check_copilot_requests()
        _pump(desktop, lambda: not desktop._busy)

        assert ran == [(case_id, request_id)]
        assert request_status(case_id, request_id, tmp_path) == {"status": "denied"}
        assert request_status(other_case, other_id, tmp_path) == {"status": "queued"}
        assert "Copilot" in desktop.status_var.get()
    finally:
        desktop.bridge.close()
        desktop.root.destroy()


def test_gui_close_cancels_claimed_copilot_request(
    tk_root, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import contextlib
    import threading
    import tkinter as tk

    from airlock.handoff import enqueue_request, request_status
    from airlock.planner import QueryProposal

    gui, desktop = _desktop(tk_root, tmp_path, monkeypatch)
    case_id = "a" * 24
    proposal = QueryProposal(operation="vm_cpu", target_alias="VM_1", time_range_minutes=30)
    started, release = threading.Event(), threading.Event()

    def blocking_run(supervisor, record, _policy, **_kwargs):
        supervisor.transition(record.request_id, "awaiting_query_approval")
        started.set()
        release.wait(timeout=5)
        return "cancelled"

    monkeypatch.setattr(gui, "run_queued_request", blocking_run)
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *_a, **_k: True)
    _, request_id = enqueue_request(
        case_id, proposal, claim_seconds=300, deadline_minutes=30, directory=tmp_path
    )
    desktop._loaded_case_id = case_id
    desktop._active_aliases = ("VM_1",)
    try:
        desktop._check_copilot_requests()
        assert started.wait(timeout=5)
        desktop._on_close()
        assert request_status(case_id, request_id, tmp_path) == {"status": "cancelled"}
    finally:
        release.set()
        desktop.bridge.close()
        with contextlib.suppress(tk.TclError):  # already destroyed by the close handler
            desktop.root.destroy()
