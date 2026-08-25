"""Tkinter manual UI for S03; all model work remains on background threads."""

from __future__ import annotations

from pathlib import Path
import threading
import tkinter as tk
from tkinter import ttk
from typing import Any

from .audio_sink import WinmmAudioSink
from .controller import FastSpeakerController
from .worker import WorkerProcess


class FastSpeakerApp:
    def __init__(self, root: tk.Tk, repo_root: Path) -> None:
        self.root, self.repo_root = root, repo_root
        self.worker = WorkerProcess(repo_root)
        self.controller: FastSpeakerController | None = None
        self.status = tk.StringVar(value="Loading Luna worker…")
        self.metrics = tk.StringVar(value="READY: loading")
        root.title("Luna FAST Speaker v1")
        root.geometry("760x460")
        self.input = tk.Text(root, height=13, wrap="word")
        self.input.pack(fill="both", expand=True, padx=12, pady=(12, 6))
        controls = ttk.Frame(root)
        controls.pack(fill="x", padx=12)
        self.speak_button = ttk.Button(controls, text="Speak", command=self.speak, state="disabled")
        self.speak_button.pack(side="left")
        ttk.Button(controls, text="Stop", command=lambda: self._call("stop")).pack(side="left", padx=4)
        ttk.Button(controls, text="Pause", command=lambda: self._call("pause")).pack(side="left", padx=4)
        ttk.Button(controls, text="Continue", command=lambda: self._call("continue_playback")).pack(side="left", padx=4)
        ttk.Button(controls, text="Replay Last Phrase", command=lambda: self._call("replay_last_phrase")).pack(side="left", padx=4)
        ttk.Button(controls, text="Replay Current Sentence", command=lambda: self._call("replay_current_sentence")).pack(side="left", padx=4)
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
            self.controller.submit(text)
            self.status.set("Queued")
        except ValueError as error:
            self.status.set(str(error))

    def _call(self, method: str) -> None:
        if self.controller is not None:
            getattr(self.controller, method)()

    def _refresh(self) -> None:
        if self.controller is not None:
            view: Any = self.controller.snapshot()
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
