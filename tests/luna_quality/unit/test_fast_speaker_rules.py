from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts.luna_quality.fast_speaker.rules import FastTestRuleOverlay, RULE_SCHEMA_VERSION


ROOT = Path(__file__).resolve().parents[3]


class FastSpeakerRulesTest(unittest.TestCase):
    def test_valid_reload_applies_only_text_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rules.json"
            path.write_text(json.dumps({"schema_version": RULE_SCHEMA_VERSION, "rules_version": "r1", "text_replacements": {"루나": "루나"}}), encoding="utf-8")
            overlay = FastTestRuleOverlay(path)
            result = overlay.reload()
        self.assertTrue(result.ok)
        self.assertFalse(result.requires_worker_restart)
        self.assertEqual(overlay.apply("루나 테스트"), "루나 테스트")

    def test_invalid_reload_keeps_previous_active_rules(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rules.json"
            path.write_text(json.dumps({"schema_version": RULE_SCHEMA_VERSION, "rules_version": "r1", "text_replacements": {"A": "B"}}), encoding="utf-8")
            overlay = FastTestRuleOverlay(path)
            self.assertTrue(overlay.reload().ok)
            path.write_text(json.dumps({"schema_version": RULE_SCHEMA_VERSION, "rules_version": "bad", "text_replacements": {}, "model": "forbidden"}), encoding="utf-8")
            result = overlay.reload()
        self.assertFalse(result.ok)
        self.assertEqual(overlay.active.rules_version, "r1")
        self.assertEqual(overlay.apply("A"), "B")

    def test_registered_issue_replaces_only_the_exact_english_sentence(self) -> None:
        path = ROOT / "scripts" / "luna_quality" / "fast_speaker" / "rules" / "fast_test_rules.json"
        overlay = FastTestRuleOverlay(path)

        result = overlay.reload()

        self.assertTrue(result.ok)
        self.assertEqual(result.active_rules_version, "issue-b7913a7e-r1")
        self.assertEqual(
            overlay.apply("I have a lot of works today."),
            "아이 have a lot of works today.",
        )
        self.assertEqual(
            overlay.apply("I have a lot of work today."),
            "I have a lot of work today.",
        )
        self.assertEqual(overlay.apply("I am busy today."), "I am busy today.")


if __name__ == "__main__":
    unittest.main()
