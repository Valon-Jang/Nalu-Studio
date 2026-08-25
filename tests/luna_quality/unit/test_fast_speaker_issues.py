from pathlib import Path
import tempfile
import unittest

from scripts.luna_quality.fast_speaker.issues import IssueCategory, IssueStore, RetestOutcome, new_issue
from scripts.luna_quality.fast_speaker.pcm import PcmFrame


class IssueTest(unittest.TestCase):
 def test_pronunciation_issue_is_self_contained_and_issue_only(self):
  issue=new_issue(category=IssueCategory.PRONUNCIATION,phrase_text="단어 검사.",note="발음 오류",seed=1,problem_word="단어",heard_as="다너",desired_pronunciation="단어")
  with tempfile.TemporaryDirectory() as d:
   folder=IssueStore(Path(d)).save(issue,PcmFrame(b"\x00\x00\x01\x00",24000))
   self.assertTrue((folder/"original_phrase.wav").exists()); self.assertIn("Candidate B",(folder/"codex_request.md").read_text())
 def test_pronunciation_requires_fields(self):
  with self.assertRaises(ValueError): IssueStore(Path(".")).save(new_issue(category=IssueCategory.PRONUNCIATION,phrase_text="x",note="x",seed=1),PcmFrame(b"\x00\x00",24000))
 def test_retest_creates_next_revision(self):
  issue=new_issue(category=IssueCategory.OTHER,phrase_text="x",note="before",seed=1)
  with tempfile.TemporaryDirectory() as d:
   store=IssueStore(Path(d)); store.save(issue,PcmFrame(b"\x00\x00",24000)); path=store.retest(issue,outcome=RetestOutcome.IMPROVED,note="after",frame=PcmFrame(b"\x00\x00",24000))
   self.assertTrue((path/"codex_request.md").exists()); self.assertEqual(path.name,"r002")
   restored=store.load(path)
   self.assertEqual(restored.issue_id,issue.issue_id); self.assertEqual(restored.revision,2); self.assertEqual(restored.outcome,RetestOutcome.IMPROVED)
 def test_codex_request_contains_complete_reproduction_and_invariants(self):
  issue=new_issue(category=IssueCategory.PRONUNCIATION,phrase_text="단어 검사.",note="발음 오류",seed=7,problem_word="단어",heard_as="다너",desired_pronunciation="단어",metadata={"current_sentence":"정확한 단어 검사.","recent_phrase_context":["앞 구절","단어 검사."],"phrase_id":"P02","source_mode":"batch","session_name":"qa","code_revision":"abc","rule_revision":"r1","metrics":{"rtf":2.0}})
  with tempfile.TemporaryDirectory() as d:
   folder=IssueStore(Path(d)).save(issue,PcmFrame(b"\x00\x00\x01\x00",24000))
   request=(folder/"codex_request.md").read_text(encoding="utf-8")
   payload=(folder/"issue.json").read_text(encoding="utf-8")
  for required in ("Exact source sentence", "Recent phrase context", "Candidate B SHA-256", "Reproduction", "Required regression", "Report changed files", "then stop"):
   self.assertIn(required,request)
  self.assertIn("evidence_paths",payload)
