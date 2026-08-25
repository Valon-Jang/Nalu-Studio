"""Issue-only evidence, revision history, and standalone Codex requests."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import json
from pathlib import Path
from uuid import uuid4
import wave

from .pcm import PcmFrame


class IssueCategory(str, Enum):
    PRONUNCIATION = "PRONUNCIATION"
    INTONATION = "INTONATION"
    PHRASE_SPLIT = "PHRASE_SPLIT"
    PACE_BREATH = "PACE_BREATH"
    OTHER = "OTHER"


class RetestOutcome(str, Enum):
    IMPROVED = "IMPROVED"
    SAME = "SAME"
    WORSE = "WORSE"
    RESOLVED = "RESOLVED"


@dataclass
class IssueRevision:
    issue_id: str
    revision: int
    category: IssueCategory
    phrase_text: str
    note: str
    seed: int
    problem_word: str | None = None
    heard_as: str | None = None
    desired_pronunciation: str | None = None
    outcome: RetestOutcome | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    def validate(self) -> None:
        if self.category is IssueCategory.PRONUNCIATION and not all((self.problem_word, self.heard_as, self.desired_pronunciation)):
            raise ValueError("pronunciation issues require problem_word, heard_as, and desired_pronunciation")


class IssueStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def save(self, issue: IssueRevision, frame: PcmFrame) -> Path:
        issue.validate()
        folder = self.root / issue.issue_id / f"r{issue.revision:03d}"
        folder.mkdir(parents=True, exist_ok=True)
        wav_path = folder / "original_phrase.wav"
        with wave.open(str(wav_path), "wb") as output:
            output.setnchannels(1); output.setsampwidth(2); output.setframerate(frame.sample_rate); output.writeframes(frame.pcm_s16le)
        payload = asdict(issue); payload["category"] = issue.category.value; payload["outcome"] = issue.outcome.value if issue.outcome else None
        (folder / "issue.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (folder / "issue.md").write_text(f"# {issue.issue_id} r{issue.revision}\n\n- Category: {issue.category.value}\n- Phrase: {issue.phrase_text}\n- Note: {issue.note}\n", encoding="utf-8")
        (folder / "codex_request.md").write_text(codex_request(issue), encoding="utf-8")
        return folder

    def retest(self, previous: IssueRevision, *, outcome: RetestOutcome, note: str, frame: PcmFrame) -> Path:
        revision = IssueRevision(
            previous.issue_id, previous.revision + 1, previous.category, previous.phrase_text,
            note, previous.seed, previous.problem_word, previous.heard_as,
            previous.desired_pronunciation, outcome, dict(previous.metadata),
        )
        return self.save(revision, frame)


def new_issue(*, category: IssueCategory, phrase_text: str, note: str, seed: int, **fields: str) -> IssueRevision:
    return IssueRevision(uuid4().hex, 1, category, phrase_text, note, seed, **fields)


def codex_request(issue: IssueRevision) -> str:
    extra = "For intonation, compare existing Luna metrics numerically before proposing a rule." if issue.category is IssueCategory.INTONATION else "For pronunciation, distinguish a repeatable lexical defect from one-off synthesis instability before any global respell change."
    return f"""# Luna FAST Speaker issue request\n\nIssue: {issue.issue_id} revision {issue.revision}\nCategory: {issue.category.value}\nPhrase: {issue.phrase_text}\nSeed: {issue.seed}\nListening note: {issue.note}\n\nEvidence is in this issue revision folder (JSON, Markdown, and issue-only WAV).\n\nInvariants: use only Chatterbox Multilingual V3 + Candidate B; do not change Candidate B, reference hash, fixed generation parameters, production pipeline, engine, or pinned runtime. Do not alter existing approved audio or normal FAST behavior. {extra}\n"""
