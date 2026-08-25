from __future__ import annotations

import json
from pathlib import Path
import tempfile
import time
import unittest

from scripts.luna_quality.fast_speaker.audio_sink import FakeAudioSink
from scripts.luna_quality.fast_speaker.batch import BatchSession, BatchState
from scripts.luna_quality.fast_speaker.contracts import FastPhrase
from scripts.luna_quality.fast_speaker.controller import FastSpeakerController
from scripts.luna_quality.fast_speaker.fast_adapter import FakeFastBackend
from scripts.luna_quality.fast_speaker.ipc import WorkerCommand
from scripts.luna_quality.fast_speaker.issues import IssueCategory, IssueStore, RetestOutcome, new_issue
from scripts.luna_quality.fast_speaker.rules import FastTestRuleOverlay, RULE_SCHEMA_VERSION
from scripts.luna_quality.fast_speaker.session_store import SessionStore
from scripts.luna_quality.fast_speaker.worker import ResidentWorker


ROOT = Path(__file__).resolve().parents[3]


class InProcessRequester:
    def __init__(self) -> None:
        self.backend = FakeFastBackend()
        self.worker = ResidentWorker(ROOT, backend_factory=lambda _: self.backend)
        self.worker.start()

    def request(self, command: WorkerCommand, timeout_seconds: float = 30.0):
        return {"status": "ok", **self.worker.dispatch(command)}


def one_phrase(text: str) -> tuple[FastPhrase, ...]:
    return (FastPhrase("P00", text, True, False),)


def wait_for(predicate) -> None:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("timed out")


class FastSpeakerHumanStyleE2ETest(unittest.TestCase):
    def test_batch_issue_reload_retest_restart_and_crash_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sessions, issues = SessionStore(root / "sessions"), IssueStore(root / "issues")
            rule_path = root / "rules.json"
            rule_path.write_text(json.dumps({"schema_version": RULE_SCHEMA_VERSION, "rules_version": "noop", "text_replacements": {}}), encoding="utf-8")
            rules = FastTestRuleOverlay(rule_path); self.assertTrue(rules.reload().ok)
            requester, audio = InProcessRequester(), FakeAudioSink()
            controller = FastSpeakerController(requester, audio, split_text=one_phrase, text_overlay=rules.apply)
            try:
                batch = BatchSession.from_text("e2e", "정상 문장.\n문제 문장.\n마지막 문장.", code_revision="S07")
                first = batch.start_next(); controller.submit(first.text)
                wait_for(lambda: len(audio.frames) == 1); controller.pause(); audio.finish()
                self.assertEqual(controller.snapshot()["state"], "paused")
                controller.continue_playback(); wait_for(lambda: controller.snapshot()["state"] == "ready")
                batch.complete_active_cleanly(); sessions.save(batch)
                self.assertEqual(batch.items[0].state, BatchState.PASS)
                synth_count = len(requester.backend.requests)
                self.assertTrue(controller.replay_last_phrase()); wait_for(lambda: len(audio.frames) == 2); audio.finish()
                self.assertTrue(controller.replay_current_sentence()); wait_for(lambda: len(audio.frames) == 3); audio.finish()
                self.assertEqual(len(requester.backend.requests), synth_count)

                second = batch.start_next(); controller.submit(second.text)
                wait_for(lambda: len(audio.frames) == 4); audio.finish(); wait_for(lambda: controller.snapshot()["state"] == "ready")
                selected = controller.recent_phrases()[-1]
                batch.pause(); batch.mark_active_issue()
                issue = new_issue(
                    category=IssueCategory.PRONUNCIATION,
                    phrase_text=selected.text,
                    note="문제 청취",
                    seed=selected.seed,
                    problem_word="문제",
                    heard_as="문재",
                    desired_pronunciation="문제",
                    metadata={"batch_sentence": second.text, "recent_phrase_context": [item.text for item in controller.recent_phrases()]},
                )
                issue_r1 = issues.save(issue, selected.frame); batch.issue_links.append(str(issue_r1)); sessions.save(batch)
                self.assertEqual(batch.items[1].state, BatchState.ISSUE)

                rule_path.write_text("{bad json", encoding="utf-8")
                self.assertFalse(rules.reload().ok); self.assertEqual(rules.active.rules_version, "noop")
                rule_path.write_text(json.dumps({"schema_version": RULE_SCHEMA_VERSION, "rules_version": "fix-1", "text_replacements": {"문제": "문제"}}), encoding="utf-8")
                self.assertTrue(rules.reload().ok)

                controller.submit(issue.phrase_text, issue.seed)
                wait_for(lambda: len(audio.frames) == 5); audio.finish(); wait_for(lambda: controller.snapshot()["state"] == "ready")
                issue_r2 = issues.retest(issue, outcome=RetestOutcome.RESOLVED, note="해결 확인", frame=controller.recent_phrases()[-1].frame)
                self.assertEqual(issues.load(issue_r2).issue_id, issue.issue_id)

                batch.resume_from_sentence(second.text)
                replayed = batch.start_next(); controller.submit(replayed.text)
                wait_for(lambda: len(audio.frames) == 6); audio.finish(); wait_for(lambda: controller.snapshot()["state"] == "ready")
                batch.complete_active_cleanly(); sessions.save(batch)
                self.assertEqual(batch.items[1].state, BatchState.PASS)

                session_before = batch.to_mapping()
                controller.replace_worker_after_restart(InProcessRequester())
                restored = sessions.load_latest()
                self.assertEqual(restored.to_mapping()["items"], session_before["items"])
                self.assertEqual(len(list(root.glob("**/*.wav"))), 2)
            finally:
                controller.close()


if __name__ == "__main__":
    unittest.main()
