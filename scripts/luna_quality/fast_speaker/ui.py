"""Tkinter manual UI for S03; all model work remains on background threads."""

from __future__ import annotations

from pathlib import Path
import subprocess
import threading
import time
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
from .rules import FastTestRuleOverlay


_CATEGORY_LABELS = {
    "발음": IssueCategory.PRONUNCIATION,
    "억양": IssueCategory.INTONATION,
    "구절 분할": IssueCategory.PHRASE_SPLIT,
    "속도·호흡": IssueCategory.PACE_BREATH,
    "기타": IssueCategory.OTHER,
}
_STATE_LABELS = {
    "READY": "준비 완료",
    "QUEUED": "대기열",
    "SYNTHESIZING": "생성 중",
    "PLAYING": "재생 중",
    "PAUSE_PENDING": "일시정지 대기",
    "PAUSED": "일시정지",
    "STOPPED": "중지됨",
}


class FastSpeakerApp:
    def __init__(self, root: tk.Tk, repo_root: Path) -> None:
        self.root, self.repo_root = root, repo_root
        self.worker = WorkerProcess(repo_root)
        self._cold_started = time.perf_counter()
        self._cold_ready_seconds: float | None = None
        self._imported_path: str | None = None
        self._code_revision = _git_revision(repo_root)
        self.controller: FastSpeakerController | None = None
        self.mode = tk.StringVar(value="manual")
        self.session_name = tk.StringVar(value=datetime.now().strftime("luna_fast_%Y%m%d_%H%M%S"))
        self.batch: BatchSession | None = None
        self.store = SessionStore(repo_root / "fast_speaker" / "sessions")
        self.issue_store = IssueStore(repo_root / "fast_speaker" / "issues")
        self.rules = FastTestRuleOverlay(repo_root / "scripts" / "luna_quality" / "fast_speaker" / "rules" / "fast_test_rules.json")
        self.last_issue = None
        self._retest_session_id: str | None = None
        self._batch_submitted = False
        self.app_state = "STARTING"
        self.status = tk.StringVar(value="루나 워커 로딩 중…")
        self.metrics = tk.StringVar(value="준비 상태: 로딩 중")
        root.title("Luna FAST Speaker v1")
        root.geometry("900x520")
        self.input = tk.Text(root, height=13, wrap="word")
        self.input.pack(fill="both", expand=True, padx=12, pady=(12, 6))
        controls = ttk.Frame(root)
        controls.pack(fill="x", padx=12)
        ttk.Radiobutton(controls, text="수동", variable=self.mode, value="manual").pack(side="left")
        ttk.Radiobutton(controls, text="배치", variable=self.mode, value="batch").pack(side="left")
        ttk.Button(controls, text="TXT/MD 불러오기", command=self.import_batch).pack(side="left", padx=6)
        ttk.Entry(controls, textvariable=self.session_name, width=24).pack(side="right")
        self.speak_button = ttk.Button(controls, text="발화", command=self.speak, state="disabled")
        self.speak_button.pack(side="left")
        playback = ttk.Frame(root)
        playback.pack(fill="x", padx=12, pady=(6, 0))
        ttk.Button(playback, text="중지", command=lambda: self._call("stop")).pack(side="left", padx=(0, 4))
        ttk.Button(playback, text="일시정지", command=lambda: self._call("pause")).pack(side="left", padx=4)
        ttk.Button(playback, text="계속", command=lambda: self._call("continue_playback")).pack(side="left", padx=4)
        ttk.Button(playback, text="마지막 구절 다시 듣기", command=lambda: self._call("replay_last_phrase")).pack(side="left", padx=4)
        ttk.Button(playback, text="현재 문장 다시 듣기", command=lambda: self._call("replay_current_sentence")).pack(side="left", padx=4)
        ttk.Button(playback, text="문제 표시", command=self.mark_issue).pack(side="left", padx=4)
        issue_controls = ttk.Frame(root)
        issue_controls.pack(fill="x", padx=12, pady=(6, 0))
        ttk.Button(issue_controls, text="개선됨", command=lambda: self.retest(RetestOutcome.IMPROVED)).pack(side="left", padx=(0, 4))
        ttk.Button(issue_controls, text="같음", command=lambda: self.retest(RetestOutcome.SAME)).pack(side="left", padx=4)
        ttk.Button(issue_controls, text="나빠짐", command=lambda: self.retest(RetestOutcome.WORSE)).pack(side="left", padx=4)
        ttk.Button(issue_controls, text="해결됨", command=lambda: self.retest(RetestOutcome.RESOLVED)).pack(side="left", padx=4)
        ttk.Button(issue_controls, text="이전 음성 듣기", command=self.listen_previous_issue).pack(side="left", padx=4)
        ttk.Button(issue_controls, text="재검증 음성 듣기", command=self.listen_latest_issue).pack(side="left", padx=4)
        maintenance = ttk.Frame(root)
        maintenance.pack(fill="x", padx=12, pady=(6, 0))
        ttk.Button(maintenance, text="규칙 다시 불러오기", command=self.reload_rules).pack(side="left", padx=(0, 4))
        ttk.Button(maintenance, text="루나 워커 재시작", command=self.restart_worker).pack(side="left", padx=4)
        ttk.Button(maintenance, text="문제 문장 재검증", command=self.retest_issue_sentence).pack(side="left", padx=4)
        ttk.Button(maintenance, text="문제 문맥부터 재개", command=self.resume_issue_context).pack(side="left", padx=4)
        ttk.Label(root, textvariable=self.status).pack(anchor="w", padx=12, pady=(8, 0))
        ttk.Label(root, textvariable=self.metrics).pack(anchor="w", padx=12, pady=(2, 12))
        root.bind_all("<Control-Return>", lambda _: self.speak())
        root.protocol("WM_DELETE_WINDOW", self.close)
        self._restore_latest_session()
        self.app_state = "LOADING_MODEL"
        threading.Thread(target=self._start_worker, daemon=True).start()
        self._refresh()

    def _start_worker(self) -> None:
        try:
            client = self.worker.start(120)
            controller = FastSpeakerController(client, WinmmAudioSink(), text_overlay=self.rules.apply)
            self.root.after(0, lambda: self._ready(controller))
        except Exception as error:
            self.root.after(0, lambda error=error: self._worker_failed(error))

    def _worker_failed(self, error: Exception) -> None:
        self.app_state = "ERROR"
        self.status.set(f"워커 오류: {type(error).__name__}: {error}")

    def _ready(self, controller: FastSpeakerController) -> None:
        self.controller = controller
        self._cold_ready_seconds = time.perf_counter() - self._cold_started
        self.app_state = "READY"
        self.status.set("준비 완료 — Ctrl+Enter 또는 발화")
        self.speak_button.configure(state="normal")

    def speak(self) -> None:
        if self.controller is None:
            return
        text = self.input.get("1.0", "end-1c")
        try:
            if self.mode.get() == "batch":
                self.batch = BatchSession.from_text(self.session_name.get(), text, source_path=self._imported_path, code_revision=self._code_revision)
                self.store.save(self.batch)
                self._start_batch_next()
            else:
                self.controller.submit(text)
            self.status.set("발화 대기열에 추가됨")
            self.app_state = "GENERATING"
        except ValueError as error:
            self.status.set(str(error))

    def _call(self, method: str) -> None:
        if self.controller is not None:
            getattr(self.controller, method)()
        if self.batch is not None and method == "pause":
            self.batch.pause(); self.store.save(self.batch)
        if self.batch is not None and method == "continue_playback":
            self.batch.continue_session(); self._start_batch_next()
        if self.batch is not None and method == "stop":
            self.batch.pause(); self.batch.recover_interrupted_active(); self._batch_submitted = False; self.store.save(self.batch)

    def import_batch(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("Text", "*.txt *.md")])
        if path:
            self._imported_path = str(Path(path).resolve())
            self.input.delete("1.0", "end")
            self.input.insert("1.0", Path(path).read_text(encoding="utf-8"))

    def mark_issue(self) -> None:
        if self.controller is None:
            return
        self.controller.pause()  # current phrase completes; next phrase is held
        self.app_state = "ISSUE_ANALYZING"
        if self.controller.snapshot()["audio_busy"]:
            self.root.after(100, self.mark_issue)
            return
        recent = self.controller.recent_phrases()
        if not recent:
            self.status.set("No completed phrase available for issue evidence")
            return
        batch_index = self.batch.active_index if self.batch is not None else None
        batch_item = self.batch.items[batch_index] if self.batch is not None and batch_index is not None else None
        if self.batch is not None:
            self.batch.pause()
            self.batch.mark_active_issue()
            self._batch_submitted = False
            self.store.save(self.batch)
        options = {f"최근 {index} | {item.phrase_id or 'P?'} | {item.text}": item for index, item in enumerate(recent, 1)}
        dialog = tk.Toplevel(self.root); dialog.title("루나 문제 표시")
        choice = tk.StringVar(value=next(reversed(options))); category = tk.StringVar(value="기타")
        note = tk.StringVar(); word = tk.StringVar(); heard = tk.StringVar(); desired = tk.StringVar()
        ttk.Label(dialog, text="문제 구절 선택 (최근 3개)").pack(anchor="w")
        ttk.Combobox(dialog, textvariable=choice, values=list(options), state="readonly", width=68).pack()
        ttk.Combobox(dialog, textvariable=category, values=list(_CATEGORY_LABELS), state="readonly").pack()
        for label, value in (("청취 메모", note), ("문제 단어", word), ("들린 발음", heard), ("원하는 발음", desired)):
            ttk.Label(dialog, text=label).pack(anchor="w"); ttk.Entry(dialog, textvariable=value, width=60).pack()
        def save() -> None:
            selected = options[choice.get()]
            fields = {"problem_word": word.get(), "heard_as": heard.get(), "desired_pronunciation": desired.get()}
            try:
                batch_sentence = batch_item.text if batch_item is not None else selected.sentence_context
                self.last_issue = new_issue(
                    category=_CATEGORY_LABELS[category.get()],
                    phrase_text=selected.text,
                    note=note.get(),
                    seed=selected.seed,
                    metadata={
                        "batch_sentence": batch_sentence,
                        "batch_item_index": batch_index,
                        "code_revision": self._code_revision,
                        "current_sentence": batch_sentence,
                        "full_phrase_split": [item.text for item in self.controller.split_text(self.rules.apply(selected.sentence_context))],
                        "engine_config": {
                            "engine": "Chatterbox Multilingual V3",
                            "reference": "Candidate B",
                            "reference_sha256": "30C6D3405F46684AF467C7D26FF40A2FB57DD48CC84CD24CF7403D9AA00A2BB9",
                            "language_id": "ko",
                            "exaggeration": 0.5,
                            "cfg": 0.5,
                            "temperature": 0.72,
                            "repetition_penalty": 1.2,
                            "min_p": 0.05,
                            "top_p": 1.0,
                        },
                        "metrics": {**dict(selected.metrics), "warm_ttfa_seconds": self.controller.snapshot()["warm_ttfa_seconds"]},
                        "original_input": self.input.get("1.0", "end-1c"),
                        "phrase_class": "sentence_final" if selected.metrics and selected.text.rstrip().endswith((".", "!", "?", "。", "！", "？")) else "continuation",
                        "phrase_id": selected.phrase_id,
                        "recent_phrase_context": [item.text for item in recent],
                        "rule_revision": self.rules.active.rules_version,
                        "session_name": self.session_name.get(),
                        "source_mode": self.mode.get(),
                    },
                    **fields,
                )
                folder = self.issue_store.save(self.last_issue, selected.frame)
                if self.batch is not None:
                    self.batch.issue_links.append(str(folder))
                    self.store.save(self.batch)
                request = (folder / "codex_request.md").read_text(encoding="utf-8")
                self.root.clipboard_clear(); self.root.clipboard_append(request)
                self.app_state = "PAUSED"
                self.status.set(f"Issue paused and request copied: {folder}"); dialog.destroy()
            except ValueError as error: self.status.set(str(error))
        ttk.Button(dialog, text="저장하고 Codex 요청 복사", command=save).pack(pady=6)

    def retest(self, outcome: RetestOutcome) -> None:
        if self.last_issue is None or self.controller is None or not self.controller.recent_phrases():
            self.status.set("Select and save an issue first"); return
        latest = self.controller.recent_phrases()[-1]
        if self._retest_session_id is None or latest.session_id != self._retest_session_id:
            self.status.set("먼저 문제 문장 재검증을 끝까지 재생하세요"); return
        frame = latest.frame
        from dataclasses import replace
        revision = replace(self.last_issue, revision=self.last_issue.revision + 1, outcome=outcome, note="Explicit user retest evaluation", status="RESOLVED" if outcome is RetestOutcome.RESOLVED else "RETESTED")
        folder = self.issue_store.save(revision, frame)
        self.last_issue = revision
        self._retest_session_id = None
        if self.batch is not None:
            self.batch.issue_links.append(str(folder))
            self.store.save(self.batch)
        self.status.set(f"Retest revision saved: {folder}")
        if outcome is RetestOutcome.RESOLVED and self.batch is not None:
            self.resume_issue_context()

    def reload_rules(self) -> None:
        self.app_state = "RELOADING_RULES"
        result = self.rules.reload()
        self.app_state = "READY" if result.ok else "ERROR"
        suffix = " Code changes require Restart Luna Worker." if result.requires_worker_restart else " Rule reload never reloads the model, reference, or generation parameters."
        self.status.set(result.message + suffix)

    def restart_worker(self) -> None:
        if self.controller is None:
            return
        self.app_state = "RESTARTING_WORKER"
        # Stop only volatile playback before the process is replaced. Persisted
        # batch and issue data stay owned by the UI and are saved below.
        self.controller.stop()
        if self.batch is not None:
            self.batch.pause()
            self.batch.recover_interrupted_active()
            self.store.save(self.batch)
            self._batch_submitted = False
        self.status.set("Restarting Luna Worker; UI, issue evidence, and saved batch state remain available…")
        def restart() -> None:
            try:
                client = self.worker.restart(120)
            except Exception as error:
                self.root.after(0, lambda error=error: self._restart_failed(error))
                return
            self.root.after(0, lambda: self._restart_ready(client))
        threading.Thread(target=restart, daemon=True).start()

    def _restart_ready(self, client: Any) -> None:
        if self.controller is not None:
            self.controller.replace_worker_after_restart(client)
        self.app_state = "READY"
        self.status.set("READY — worker restarted. Continue batch to replay the interrupted sentence from its beginning.")

    def _restart_failed(self, error: Exception) -> None:
        self.app_state = "ERROR"
        self.status.set(f"Worker restart failed; saved session is unchanged: {type(error).__name__}: {error}")

    def retest_issue_sentence(self) -> None:
        if self.last_issue is None or self.controller is None:
            self.status.set("Select and save an issue first"); return
        self.controller.stop()
        self._retest_session_id = self.controller.submit(self.last_issue.phrase_text, self.last_issue.seed)
        self.status.set("Retesting the saved issue sentence with the original seed")

    def resume_issue_context(self) -> None:
        if self.last_issue is None or self.batch is None:
            self.status.set("No saved issue and active batch context"); return
        sentence = str(self.last_issue.metadata.get("batch_sentence", self.last_issue.phrase_text))
        try:
            self.batch.resume_from_sentence(sentence)
            self.store.save(self.batch)
            self._batch_submitted = False
            self._start_batch_next()
            self.status.set("Resuming batch from the beginning of the issue sentence")
        except ValueError as error:
            self.status.set(str(error))

    def listen_issue(self, revision: int) -> None:
        if self.last_issue is None:
            self.status.set("No issue selected"); return
        path = self.issue_store.root / self.last_issue.issue_id / f"r{revision:03d}" / "original_phrase.wav"
        if path.exists():
            import winsound
            winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)
        else: self.status.set(f"Issue revision not available: r{revision:03d}")

    def listen_previous_issue(self) -> None:
        if self.last_issue is not None:
            self.listen_issue(max(1, self.last_issue.revision - 1))

    def listen_latest_issue(self) -> None:
        if self.last_issue is not None:
            self.listen_issue(self.last_issue.revision)

    def _restore_latest_session(self) -> None:
        recovered = self.store.load_latest()
        if recovered is None:
            return
        self.batch = recovered
        self.mode.set("batch")
        self.session_name.set(recovered.name)
        self._imported_path = recovered.source_path
        self.input.delete("1.0", "end")
        self.input.insert("1.0", recovered.source_text)
        if recovered.issue_links:
            try:
                self.last_issue = self.issue_store.load(Path(recovered.issue_links[-1]))
            except (OSError, ValueError, KeyError, TypeError):
                self.last_issue = None
        self.status.set("Recovered saved batch; press Continue to resume from the interrupted sentence")

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
            counts = f" | batch {dict(self.batch.counts())}" if self.batch is not None else ""
            if self.app_state not in {"RESTARTING_WORKER", "RELOADING_RULES", "ISSUE_ANALYZING", "ERROR"}:
                self.app_state = str(view["state"]).upper()
                self.status.set(f"{_STATE_LABELS.get(self.app_state, self.app_state)} | 대기 {view['queue_runs']}{counts}")
            last = view["last_metrics"] or {}
            self.metrics.set(
                f"콜드 준비: {self._cold_ready_seconds} | 웜 TTFA: {view['warm_ttfa_seconds']} | "
                f"합성: {last.get('generation_seconds')} | 음성 길이: {last.get('audio_duration_seconds')} | "
                f"구절 RTF: {last.get('rtf')} | 평균 RTF: {view['average_rtf']} | "
                f"구절 간 공백: {view['inter_phrase_gaps_seconds']} | 언더런: {view['underrun_count']}"
            )
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


def _git_revision(repo_root: Path) -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"
