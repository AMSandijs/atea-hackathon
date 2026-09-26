"""Single-user local desktop UI for the supervised investigation workflow."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from dataclasses import dataclass, field
from tkinter import messagebox, ttk
from typing import Literal

from .broker import BrokerError, QueryReview, case_capabilities
from .cases import case_directory, read_case
from .config import load_policy
from .investigation import InvestigationTurn, run_investigation_turn
from .models import Sanitized
from .scope import ScopeReview, create_case_scope

_ApprovalKind = Literal["query", "result"]


@dataclass
class _PendingApproval:
    kind: _ApprovalKind
    payload: object
    completed: threading.Event = field(default_factory=threading.Event)
    approved: bool = False


class ApprovalBridge:
    """Move approval requests from one worker to the trusted local UI thread."""

    def __init__(self, timeout_seconds: float = 600.0) -> None:
        self._requests: queue.Queue[_PendingApproval] = queue.Queue()
        self._lock = threading.Lock()
        self._pending: dict[int, _PendingApproval] = {}
        self._closed = False
        self._timeout_seconds = timeout_seconds

    def approve_query(self, review: QueryReview) -> bool:
        return self._request("query", review)

    def approve_result(self, raw_result: str, sanitized: Sanitized) -> bool:
        return self._request("result", (raw_result, sanitized))

    def _request(self, kind: _ApprovalKind, payload: object) -> bool:
        with self._lock:
            if self._closed:
                return False
            request = _PendingApproval(kind, payload)
            self._pending[id(request)] = request
            self._requests.put(request)
        if not request.completed.wait(self._timeout_seconds):
            with self._lock:
                request.approved = False
                request.completed.set()
        with self._lock:
            self._pending.pop(id(request), None)
            return request.approved is True

    def drain(self, review: object, limit: int = 8) -> int:
        """Resolve queued requests on the caller thread; every exception denies."""

        handled = 0
        for _ in range(limit):
            try:
                request = self._requests.get_nowait()
            except queue.Empty:
                break
            with self._lock:
                if request.completed.is_set():
                    handled += 1
                    continue
                closed = self._closed
                if closed:
                    request.approved = False
                    request.completed.set()
                    handled += 1
                    continue
            try:
                accepted = review(request) is True
            except Exception:  # noqa: BLE001 — approval UI failures must deny, never release.
                accepted = False
            with self._lock:
                if not self._closed and not request.completed.is_set():
                    request.approved = accepted
                else:
                    request.approved = False
                request.completed.set()
            handled += 1
        return handled

    def close(self) -> None:
        """Reject queued requests and all future approval requests."""

        with self._lock:
            self._closed = True
            for request in self._pending.values():
                request.approved = False
                request.completed.set()
        while True:
            try:
                request = self._requests.get_nowait()
            except queue.Empty:
                break
            request.approved = False
            request.completed.set()


class AirlockDesktop:
    """Focused GUI over existing case, scope, broker, and evidence APIs."""

    def __init__(self, root: tk.Tk | None = None) -> None:
        self.root = root or tk.Tk()
        self.root.title("Local AI Airlock — Investigation")
        self.root.geometry("980x740")
        self.root.minsize(780, 600)
        self.bridge = ApprovalBridge()
        self._events: queue.Queue[tuple[str, object]] = queue.Queue()
        self._targets: dict[str, str] = {}
        self._busy = False
        self._closing = False
        self._loaded_case_id: str | None = None
        self._active_aliases: tuple[str, ...] = ()

        self._build()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(60, self._poll)

    def _build(self) -> None:
        style = ttk.Style(self.root)
        style.configure("Title.TLabel", font=("Segoe UI", 17, "bold"))
        style.configure("Hint.TLabel", foreground="#526170")

        outer = ttk.Frame(self.root, padding=16)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="Local AI Airlock", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            outer,
            text="Azure reads stay local until you approve sanitized evidence for Copilot.",
            style="Hint.TLabel",
        ).pack(anchor="w", pady=(2, 14))

        case_frame = ttk.LabelFrame(outer, text="1 · Approved case", padding=10)
        case_frame.pack(fill="x", pady=(0, 10))
        self.case_var = tk.StringVar()
        ttk.Entry(case_frame, textvariable=self.case_var).pack(side="left", fill="x", expand=True)
        self.load_button = ttk.Button(case_frame, text="Load case", command=self._load_case)
        self.load_button.pack(side="left", padx=(8, 0))
        self.case_status = ttk.Label(
            outer, text="Enter the case ID created by Airlock.", style="Hint.TLabel"
        )
        self.case_status.pack(anchor="w", pady=(0, 10))

        scope_frame = ttk.LabelFrame(outer, text="2 · Private Azure scope", padding=10)
        scope_frame.pack(fill="x", pady=(0, 10))
        row = ttk.Frame(scope_frame)
        row.pack(fill="x")
        self.alias_var = tk.StringVar()
        self.resource_var = tk.StringVar()
        ttk.Label(row, text="Alias").pack(side="left")
        self.alias_entry = ttk.Entry(row, textvariable=self.alias_var, width=12)
        self.alias_entry.pack(side="left", padx=(5, 12))
        ttk.Label(row, text="ARM resource ID (masked while entering)").pack(side="left")
        self.resource_entry = ttk.Entry(row, textvariable=self.resource_var, show="*", width=48)
        self.resource_entry.pack(side="left", fill="x", expand=True, padx=(5, 8))
        self.add_target_button = ttk.Button(row, text="Add", command=self._add_target)
        self.add_target_button.pack(side="left")
        self.remove_target_button = ttk.Button(
            row, text="Remove last", command=self._remove_last_target, state="disabled"
        )
        self.remove_target_button.pack(side="left", padx=(6, 0))
        self.targets_label = ttk.Label(scope_frame, text="No targets entered.", style="Hint.TLabel")
        self.targets_label.pack(anchor="w", pady=(8, 4))
        scope_actions = ttk.Frame(scope_frame)
        scope_actions.pack(fill="x")
        self.expiry_var = tk.StringVar(value="240")
        ttk.Label(scope_actions, text="Scope lifetime (minutes)").pack(side="left")
        self.expiry_entry = ttk.Entry(scope_actions, textvariable=self.expiry_var, width=8)
        self.expiry_entry.pack(side="left", padx=6)
        self.scope_button = ttk.Button(
            scope_actions, text="Review and approve scope", command=self._approve_scope
        )
        self.scope_button.pack(side="left", padx=(4, 0))

        goal_frame = ttk.LabelFrame(outer, text="3 · Copilot's next alias-only request", padding=10)
        goal_frame.pack(fill="both", expand=True, pady=(0, 10))
        self.goal_text = tk.Text(goal_frame, height=5, wrap="word", undo=False)
        self.goal_text.pack(fill="both", expand=True)
        controls = ttk.Frame(outer)
        controls.pack(fill="x")
        self.rules_only_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            controls,
            text="Rules-only evidence scan (local planner is still required)",
            variable=self.rules_only_var,
        ).pack(side="left")
        self.run_button = ttk.Button(
            controls, text="Propose and run one read", command=self._start_turn, state="disabled"
        )
        self.run_button.pack(side="right")

        self.status_var = tk.StringVar(value="Idle")
        ttk.Label(outer, textvariable=self.status_var, style="Hint.TLabel").pack(
            anchor="w", pady=(10, 2)
        )
        evidence_row = ttk.Frame(outer)
        evidence_row.pack(fill="x")
        ttk.Label(evidence_row, text="Released evidence ID").pack(side="left")
        self.evidence_var = tk.StringVar()
        ttk.Entry(evidence_row, textvariable=self.evidence_var, state="readonly").pack(
            side="left", fill="x", expand=True, padx=8
        )
        self.copy_button = ttk.Button(
            evidence_row, text="Copy ID", command=self._copy_evidence, state="disabled"
        )
        self.copy_button.pack(side="right")

    def _load_case(self) -> None:
        case_id = self.case_var.get().strip()
        try:
            read_case(case_id)
        except (OSError, ValueError, TypeError) as exc:
            self._show_error("Case unavailable", str(exc))
            return
        if case_id != self._loaded_case_id:
            self._targets.clear()
            self._update_pending_targets()
        self._loaded_case_id = case_id
        self._active_aliases = ()
        try:
            self._active_aliases = tuple(sorted(case_capabilities(case_id)))
        except BrokerError:
            scope_file = case_directory() / f"{case_id}.scope.json"
            if scope_file.exists():
                self.case_status.configure(
                    text="This case has an expired or invalid scope. Create a new case to continue."
                )
                self._set_scope_enabled(False)
                self.run_button.configure(state="disabled")
                return
        if self._active_aliases:
            self._targets.clear()
            self.case_status.configure(
                text=f"Approved case loaded · allowed aliases: {', '.join(self._active_aliases)}"
            )
            self.targets_label.configure(
                text="Existing approved scope · " + ", ".join(self._active_aliases)
            )
            self._set_scope_enabled(False)
            self.run_button.configure(state="normal")
        else:
            self.case_status.configure(
                text="Approved case loaded · add and approve its private resource scope."
            )
            self._set_scope_enabled(True)
            self.run_button.configure(state="disabled")

    def _set_scope_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self.alias_entry.configure(state=state)
        self.resource_entry.configure(state=state)
        self.add_target_button.configure(state=state)
        self.remove_target_button.configure(state=state if self._targets else "disabled")
        self.expiry_entry.configure(state=state)
        self.scope_button.configure(state=state)

    def _add_target(self) -> None:
        alias = self.alias_var.get().strip()
        resource_id = self.resource_var.get().strip()
        if not alias or not resource_id:
            self._show_error("Incomplete target", "Enter both an alias and an ARM resource ID.")
            return
        if alias in self._targets:
            self._show_error("Duplicate alias", "Each scope alias must be unique.")
            return
        self._targets[alias] = resource_id
        self.alias_var.set("")
        self.resource_var.set("")
        self._update_pending_targets()

    def _remove_last_target(self) -> None:
        if self._targets:
            self._targets.pop(next(reversed(self._targets)))
        self._update_pending_targets()

    def _update_pending_targets(self) -> None:
        aliases = ", ".join(sorted(self._targets))
        self.targets_label.configure(
            text=f"Pending local targets: {aliases}" if aliases else "No targets entered."
        )
        self.remove_target_button.configure(state="normal" if self._targets else "disabled")

    def _approve_scope(self) -> None:
        case_id = self._loaded_case_id
        if case_id is None or not self._targets:
            self._show_error(
                "Scope not ready", "Load an approved case and add at least one target."
            )
            return
        try:
            expires = int(self.expiry_var.get())
            approved = create_case_scope(
                case_id,
                self._targets,
                approve_scope=self._review_scope,
                expires_in_minutes=expires,
            )
        except (RuntimeError, ValueError) as exc:
            self._show_error("Scope was not saved", str(exc))
            return
        self._active_aliases = tuple(target.alias for target in approved.targets)
        self._targets.clear()
        self.targets_label.configure(text="Approved aliases: " + ", ".join(self._active_aliases))
        self.case_status.configure(text="Scope approved and saved locally.")
        self._set_scope_enabled(False)
        self.run_button.configure(state="normal")

    @staticmethod
    def _review_scope(review: ScopeReview) -> bool:
        lines = [f"Expires: {review.expires_at.isoformat()}", "", "Resources and allowed reads:"]
        lines.extend(
            f"{target.alias}: {target.resource_id} ({', '.join(target.operations)})."
            for target in review.targets
        )
        return messagebox.askyesno(
            "Approve private Azure scope",
            "\n".join(lines),
            icon="warning",
            default=messagebox.NO,
        )

    def _start_turn(self) -> None:
        if self._busy or self._closing:
            return
        case_id = self._loaded_case_id
        goal = self.goal_text.get("1.0", "end").strip()
        if case_id is None or not self._active_aliases:
            self._show_error("Scope required", "Load an approved case and approve its scope first.")
            return
        if not goal:
            self._show_error(
                "Request required", "Paste one alias-only next-read request from Copilot."
            )
            return
        self._busy = True
        self.run_button.configure(state="disabled")
        self.status_var.set("Local planner is preparing one bounded proposal…")
        worker = threading.Thread(
            target=self._run_turn_worker,
            args=(case_id, goal, self.rules_only_var.get()),
            name="airlock-investigation",
            daemon=True,
        )
        worker.start()

    def _run_turn_worker(self, case_id: str, goal: str, rules_only: bool) -> None:
        try:
            turn = run_investigation_turn(
                case_id,
                goal,
                load_policy(),
                approve_query=self.bridge.approve_query,
                approve_result=self.bridge.approve_result,
                allow_rules_only=rules_only,
            )
            self._events.put(("turn", turn))
        except Exception as exc:  # noqa: BLE001 — surface worker failures and keep the UI fail-closed.
            self._events.put(("error", str(exc)))

    def _poll(self) -> None:
        self.bridge.drain(self._present_approval)
        while True:
            try:
                event, payload = self._events.get_nowait()
            except queue.Empty:
                break
            if event == "turn":
                self._finish_turn(payload)
            elif event == "error":
                self._busy = False
                self.run_button.configure(state="normal" if self._active_aliases else "disabled")
                self.status_var.set("Turn stopped; no evidence was released.")
                if not self._closing:
                    self._show_error("Investigation stopped", str(payload))
        if self._closing and not self._busy:
            self.root.destroy()
            return
        self.root.after(60, self._poll)

    def _present_approval(self, request: _PendingApproval) -> bool:
        if self._closing:
            return False
        if request.kind == "query":
            review = request.payload
            if not isinstance(review, QueryReview):
                return False
            self.status_var.set("Waiting for local Azure query approval…")
            detail = (
                f"Alias: {review.target_alias}\n"
                f"Real resource ID: {review.resource_id}\n"
                f"Read operation: {review.operation}\n"
                f"Time window: last {review.time_range_minutes} minutes\n\n"
                "Only this fixed read will run. Approve it?"
            )
            return messagebox.askyesno(
                "Approve one Azure read",
                detail,
                parent=self.root,
                icon="warning",
                default=messagebox.NO,
            )
        if (
            request.kind == "result"
            and isinstance(request.payload, tuple)
            and len(request.payload) == 2
        ):
            raw_result, sanitized = request.payload
            if isinstance(raw_result, str) and isinstance(sanitized, Sanitized):
                self.status_var.set("Waiting for separate sanitized-result approval…")
                return self._review_result(raw_result, sanitized)
        return False

    def _review_result(self, raw_result: str, sanitized: Sanitized) -> bool:
        dialog = tk.Toplevel(self.root)
        dialog.title("Review Azure evidence before release")
        dialog.geometry("1050x680")
        dialog.transient(self.root)
        dialog.grab_set()
        frame = ttk.Frame(dialog, padding=12)
        frame.pack(fill="both", expand=True)
        if sanitized.blocked:
            warning = (
                "Blocked secret detected — this result cannot be released. Rotate the credential."
            )
            ttk.Label(frame, text=warning, foreground="#a00000", wraplength=1000).pack(
                anchor="w", pady=(0, 8)
            )
        else:
            ttk.Label(
                frame,
                text="Compare the local Azure response with the exact sanitized text Copilot would receive.",
                wraplength=1000,
            ).pack(anchor="w", pady=(0, 8))

        findings = sanitized.findings[:40]
        summary = (
            "; ".join(f"{item.tier}/{item.entity_type}: {item.text}" for item in findings)
            or "No detector findings. Human review is still required."
        )
        if len(sanitized.findings) > len(findings):
            summary += f"; plus {len(sanitized.findings) - len(findings)} more finding(s)"
        ttk.Label(frame, text=summary, wraplength=1000, foreground="#526170").pack(
            anchor="w", pady=(0, 8)
        )

        panes = ttk.Panedwindow(frame, orient="horizontal")
        panes.pack(fill="both", expand=True)
        self._add_text_pane(panes, "Raw result — local only", raw_result)
        self._add_text_pane(panes, "Sanitized release candidate", sanitized.text)

        outcome = {"approved": False}
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(10, 0))
        approve_button = ttk.Button(
            buttons,
            text="Approve release to Copilot",
            command=lambda: self._close_review(dialog, outcome, True),
            state="disabled" if sanitized.blocked else "normal",
        )
        approve_button.pack(side="right")
        ttk.Button(
            buttons,
            text="Reject",
            command=lambda: self._close_review(dialog, outcome, False),
        ).pack(side="right", padx=(0, 8))
        dialog.protocol("WM_DELETE_WINDOW", lambda: self._close_review(dialog, outcome, False))
        dialog.wait_window()
        return outcome["approved"]

    @staticmethod
    def _close_review(dialog: tk.Toplevel, outcome: dict[str, bool], approved: bool) -> None:
        outcome["approved"] = approved
        dialog.destroy()

    @staticmethod
    def _add_text_pane(parent: ttk.Panedwindow, title: str, text: str) -> None:
        pane = ttk.Frame(parent, padding=4)
        ttk.Label(pane, text=title).pack(anchor="w", pady=(0, 4))
        content = ttk.Frame(pane)
        content.pack(fill="both", expand=True)
        editor = tk.Text(content, wrap="none", undo=False)
        vertical = ttk.Scrollbar(content, orient="vertical", command=editor.yview)
        horizontal = ttk.Scrollbar(content, orient="horizontal", command=editor.xview)
        editor.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        editor.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        content.rowconfigure(0, weight=1)
        content.columnconfigure(0, weight=1)
        editor.insert("1.0", text)
        editor.configure(state="disabled")
        parent.add(pane, weight=1)

    def _finish_turn(self, payload: object) -> None:
        self._busy = False
        self.run_button.configure(state="normal" if self._active_aliases else "disabled")
        if not isinstance(payload, InvestigationTurn):
            self.status_var.set("Turn stopped; no evidence was released.")
            return
        if payload.status == "released" and payload.evidence_id is not None:
            self.evidence_var.set(payload.evidence_id)
            self.copy_button.configure(state="normal")
            self.status_var.set(
                f"Evidence approved for MCP. Operation: {payload.proposal.operation}; "
                f"target: {payload.proposal.target_alias}."
            )
        else:
            explanations = {
                "proposal_rejected": "The local planner rejected the request; no Azure read ran.",
                "query_denied": "Query approval was denied; no Azure read ran.",
                "result_not_released": "The result was blocked or not approved; no evidence was released.",
            }
            self.status_var.set(explanations.get(payload.status, "No evidence was released."))

    def _copy_evidence(self) -> None:
        evidence_id = self.evidence_var.get()
        if not evidence_id:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(evidence_id)
        self.status_var.set("Opaque evidence ID copied. Share only this ID with Copilot.")

    def _on_close(self) -> None:
        if self._busy:
            close = messagebox.askyesno(
                "Stop Airlock review?",
                "Any pending approval will be rejected. A read already approved may finish locally, "
                "but its result will not be released. Close when the read finishes?",
                parent=self.root,
                default=messagebox.NO,
            )
            if not close:
                return
            self._closing = True
            self.bridge.close()
            self.run_button.configure(state="disabled")
            self.status_var.set(
                "Closing after pending local work stops; no further results will be released."
            )
            return
        self._closing = True
        self.bridge.close()
        self.root.destroy()

    def _show_error(self, title: str, message: str) -> None:
        messagebox.showerror(title, message, parent=self.root)

    def run(self) -> None:
        self.root.mainloop()


def launch_gui() -> None:
    """Create and run the local desktop supervisor."""

    AirlockDesktop().run()
