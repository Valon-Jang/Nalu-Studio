"""Tkinter manual UI for S03; all model work remains on background threads."""

from __future__ import annotations

from pathlib import Path
import threading
import tkinter as tk
from tkinter import filedialog, ttk
from typing import Any
from datetime import datetime

from .audio_sink import WinmmAudioSink
from .batch import BatchSession
from .controller import FastSpeakerController
from .session_store import SessionStore
from .worker import WorkerProcess
from .issues import IssueCategory, IssueStore, RetestOutcome, new_issue


class FastSpeakerApp:
    def __init__(self, root: tk.Tk, repo_root: Path) -> None:
        self.root, self.repo_root = root, repo_root
        self.worker = WorkerProcess(repo_root)
        self.controller: FastSpeakerController | None = None
        self.mode = tk.StringVar(value="manual")
        self.session_name = tk.StringVar(value=datetime.now().strftime("luna_fast_%Y%m%d_%H%M%S"))
        self.batch: BatchSession | None = None
        self.store = SessionStore(repo_root / "fast_speaker" / "sessions")
        self.issue_store = IssueStore(repo_root / "fast_speaker" / "issues")
        self.last_issue = None
        self._batch_submitted = False
        self.status = tk.StringVar(value="Loading Luna worker…")
        self.metrics = tk.StringVar(value="READY: loading")
        root.title("Luna FAST Speaker v1")
        root.geometry("760x460")
        self.input = tk.Text(root, height=13, wrap="word")
        self.input.pack(fill="both", expand=True, padx=12, pady=(12, 6))
        controls = ttk.Frame(root)
        controls.pack(fill="x", padx=12)
        ttk.Radiobutton(controls, text="Manual", variable=self.mode, value="manual").pack(side="left")
        ttk.Radiobutton(controls, text="Batch", variable=self.mode, value="batch").pack(side="left")
        ttk.Button(controls, text="Import .txt/.md", command=self.import_batch).pack(side="left", padx=6)
        ttk.Entry(controls, textvariable=self.session_name, width=24).pack(side="right")
        self.speak_button = ttk.Button(controls, text="Speak", command=self.speak, state="disabled")
        self.speak_button.pack(side="left")
        ttk.Button(controls, text="Stop", command=lambda: self._call("stop")).pack(side="left", padx=4)
        ttk.Button(controls, text="Pause", command=lambda: self._call("pause")).pack(side="left", padx=4)
        ttk.Button(controls, text="Continue", command=lambda: self._call("continue_playback")).pack(side="left", padx=4)
        ttk.Button(controls, text="Replay Last Phrase", command=lambda: self._call("replay_last_phrase")).pack(side="left", padx=4)
        ttk.Button(controls, text="Replay Current Sentence", command=lambda: self._call("replay_current_sentence")).pack(side="left", padx=4)
        ttk.Button(controls, text="Mark Issue", command=self.mark_issue).pack(side="left", padx=4)
        ttk.Button(controls, text="Retest Improved", command=lambda: self.retest(RetestOutcome.IMPROVED)).pack(side="left", padx=4)
        ttk.Button(controls, text="Listen Previous", command=lambda: self.listen_issue(1)).pack(side="left", padx=4)
        ttk.Button(controls, text="Listen Retest", command=lambda: self.listen_issue(2)).pack(side="left", padx=4)
        ttk.Label(root, textvariable=self.status).pack(anchor="w", padx=12, pady=(8, 0))
        ttk.Label(root, textvariable=self.metrics).pack(anchor="w", padx=12, pady=(2, 12))
        root.bind_all("<Control-Return>", lambda _: self.speak())
        root.protocol("WM_DELETE_WINDOW", self.close)
        threading.Thread(target=self._start_worker, daemon=True).start()
        self._refresh()

    def _start_worker(self) -> None:
        try:
            client = self.worker.start(120)
            controller = FastSpeakerController(client, WinmmAudioSink())
            self.root.after(0, lambda: self._ready(controller))
        except Exception as error:
            self.root.after(0, lambda: self.status.set(f"Worker error: {type(error).__name__}: {error}"))

    def _ready(self, controller: FastSpeakerController) -> None:
        self.controller = controller
        self.status.set("READY — Ctrl+Enter 또는 Speak")
        self.speak_button.configure(state="normal")

    def speak(self) -> None:
        if self.controller is None:
            return
        text = self.input.get("1.0", "end-1c")
        try:
            if self.mode.get() == "batch":
                self.batch = BatchSession.from_text(self.session_name.get(), text)
                self.store.save(self.batch)
                self._start_batch_next()
            else:
                self.controller.submit(text)
            self.status.set("Queued")
        except ValueError as error:
            self.status.set(str(error))

    def _call(self, method: str) -> None:
        if self.controller is not None:
            getattr(self.controller, method)()
        if self.batch is not None and method == "pause":
            self.batch.pause(); self.store.save(self.batch)
        if self.batch is not None and method == "continue_playback":
            self.batch.continue_session(); self._start_batch_next()

    def import_batch(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("Text", "*.txt *.md")])
        if path:
            self.input.delete("1.0", "end")
            self.input.insert("1.0", Path(path).read_text(encoding="utf-8"))

    def mark_issue(self) -> None:
        if self.controller is None:
            return
        self.controller.pause()  # current phrase completes; next phrase is held
        recent = self.controller.recent_phrases()
        if not recent:
            self.status.set("No completed phrase available for issue evidence")
            return
        dialog = tk.Toplevel(self.root); dialog.title("Mark Luna Issue")
        choice = tk.StringVar(value=recent[-1][0]); category = tk.StringVar(value=IssueCategory.OTHER.value)
        note = tk.StringVar(); word = tk.StringVar(); heard = tk.StringVar(); desired = tk.StringVar()
        ttk.Label(dialog, text="Primary phrase (recent 3)").pack(anchor="w")
        ttk.Combobox(dialog, textvariable=choice, values=[x[0] for x in recent], state="readonly", width=58).pack()
        ttk.Combobox(dialog, textvariable=category, values=[x.value for x in IssueCategory], state="readonly").pack()
        for label, value in (("Listening note", note), ("Problem word", word), ("Heard as", heard), ("Desired pronunciation", desired)):
            ttk.Label(dialog, text=label).pack(anchor="w"); ttk.Entry(dialog, textvariable=value, width=60).pack()
        def save() -> None:
            text, frame, seed = next(x for x in recent if x[0] == choice.get())
            fields = {"problem_word": word.get(), "heard_as": heard.get(), "desired_pronunciation": desired.get()}
            try:
                self.last_issue = new_issue(category=IssueCategory(category.get()), phrase_text=text, note=note.get(), seed=seed, **fields)
                folder = self.issue_store.save(self.last_issue, frame)
                request = (folder / "codex_request.md").read_text(encoding="utf-8")
                self.root.clipboard_clear(); self.root.clipboard_append(request)
                self.status.set(f"Issue paused and request copied: {folder}"); dialog.destroy()
            except ValueError as error: self.status.set(str(error))
        ttk.Button(dialog, text="Save + Copy Codex Request", command=save).pack(pady=6)

    def retest(self, outcome: RetestOutcome) -> None:
        if self.last_issue is None or self.controller is None or not self.controller.recent_phrases():
            self.status.set("Select and save an issue first"); return
        _, frame, _ = self.controller.recent_phrases()[-1]
        folder = self.issue_store.retest(self.last_issue, outcome=outcome, note="Explicit user retest evaluation", frame=frame)
        self.status.set(f"Retest revision saved: {folder}")

    def listen_issue(self, revision: int) -> None:
        if self.last_issue is None:
            self.status.set("No issue selected"); return
        path = self.issue_store.root / self.last_issue.issue_id / f"r{revision:03d}" / "original_phrase.wav"
        if path.exists():
            import winsound
            winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)
        else: self.status.set(f"Issue revision not available: r{revision:03d}")

    def _start_batch_next(self) -> None:
        if self.controller is None or self.batch is None or self.batch.paused or self._batch_submitted:
            return
        item = self.batch.start_next()
        if item is not None:
            self.store.save(self.batch)
            self._batch_submitted = True
            self.controller.submit(item.text)

    def _refresh(self) -> None:
        if self.controller is not None:
            view: Any = self.controller.snapshot()
            if self.batch is not None and self._batch_submitted and not view["audio_busy"] and not view["synthesis_busy"] and view["state"] == "ready":
                self.batch.complete_active_cleanly()
                self.store.save(self.batch)
                self._batch_submitted = False
                self._start_batch_next()
            self.status.set(f"{view['state']} | queue {view['queue_runs']}")
            self.metrics.set(f"warm TTFA: {view['warm_ttfa_seconds']} | avg RTF: {view['average_rtf']} | last: {view['last_metrics']}")
        self.root.after(150, self._refresh)

    def close(self) -> None:
        if self.controller is not None:
            self.controller.close()
        self.worker.shutdown()
        self.root.destroy()


def run(repo_root: Path) -> None:
    root = tk.Tk()
    FastSpeakerApp(root, repo_root)
    root.mainloop()
