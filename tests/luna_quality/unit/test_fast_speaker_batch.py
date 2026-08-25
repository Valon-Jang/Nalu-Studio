from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from scripts.luna_quality.fast_speaker.batch import BatchSession, BatchState, parse_batch_text
from scripts.luna_quality.fast_speaker.session_store import SessionStore


class FastSpeakerBatchTest(unittest.TestCase):
    def test_newline_first_parser_preserves_order(self) -> None:
        self.assertEqual(parse_batch_text("첫 줄입니다. 다음 문장!\n둘째 줄은 유지됩니다"), ["첫 줄입니다.", "다음 문장!", "둘째 줄은 유지됩니다"])

    def test_pause_blocks_auto_pass_and_recovery_replays_active_sentence(self) -> None:
        session = BatchSession.from_text("session", "하나.\n둘.")
        active = session.start_next()
        self.assertEqual(active.text, "하나.")
        session.pause()
        session.complete_active_cleanly()
        self.assertEqual(session.items[0].state, BatchState.PLAYING)
        with tempfile.TemporaryDirectory() as directory:
            store = SessionStore(Path(directory))
            path = store.save(session)
            restored = store.load(path)
        self.assertTrue(restored.recovered)
        self.assertEqual(restored.items[0].state, BatchState.PENDING)
        self.assertIsNone(restored.active_index)
        restored.continue_session()
        self.assertEqual(restored.start_next().text, "하나.")

    def test_clean_completion_auto_passes(self) -> None:
        session = BatchSession.from_text("session", "하나.")
        session.start_next()
        session.complete_active_cleanly()
        self.assertEqual(session.counts()["PASS"], 1)

    def test_resume_issue_context_replays_the_problem_sentence(self) -> None:
        session = BatchSession.from_text("session", "앞 문장.\n문제 문장.\n뒤 문장.")
        first = session.start_next(); self.assertEqual(first.text, "앞 문장.")
        session.complete_active_cleanly()
        active = session.start_next(); self.assertEqual(active.text, "문제 문장.")
        session.pause(); session.recover_interrupted_active()
        chosen = session.resume_from_sentence("문제 문장.")
        self.assertEqual(chosen.text, "문제 문장.")
        self.assertEqual(session.start_next().text, "문제 문장.")

    def test_restart_preparation_persists_interrupted_sentence_as_pending(self) -> None:
        session = BatchSession.from_text("session", "재시작 문장.")
        session.start_next()
        session.pause(); session.recover_interrupted_active()
        with tempfile.TemporaryDirectory() as directory:
            store = SessionStore(Path(directory))
            restored = store.load(store.save(session))
        self.assertTrue(restored.paused)
        self.assertEqual(restored.items[0].state, BatchState.PENDING)


if __name__ == "__main__":
    unittest.main()
