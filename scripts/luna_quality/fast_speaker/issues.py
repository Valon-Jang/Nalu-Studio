"""Issue-only evidence, revision history, and standalone Codex requests."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
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
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    status: str = "OPEN"

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
        payload["evidence_paths"] = {"issue_wav": str(wav_path), "issue_markdown": str(folder / "issue.md"), "codex_request": str(folder / "codex_request.md")}
        (folder / "issue.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (folder / "issue.md").write_text(f"# {issue.issue_id} r{issue.revision}\n\n- Status: {issue.status}\n- Category: {issue.category.value}\n- Phrase: {issue.phrase_text}\n- Note: {issue.note}\n- Seed: {issue.seed}\n- Evidence: `{wav_path}`\n", encoding="utf-8")
        (folder / "codex_request.md").write_text(codex_request(issue, wav_path), encoding="utf-8")
        return folder

    def retest(self, previous: IssueRevision, *, outcome: RetestOutcome, note: str, frame: PcmFrame) -> Path:
        revision = IssueRevision(
            issue_id=previous.issue_id,
            revision=previous.revision + 1,
            category=previous.category,
            phrase_text=previous.phrase_text,
            note=note,
            seed=previous.seed,
            problem_word=previous.problem_word,
            heard_as=previous.heard_as,
            desired_pronunciation=previous.desired_pronunciation,
            outcome=outcome,
            metadata=dict(previous.metadata),
            status="RESOLVED" if outcome is RetestOutcome.RESOLVED else "RETESTED",
        )
        return self.save(revision, frame)

    def load(self, folder: Path) -> IssueRevision:
        payload = json.loads((folder / "issue.json").read_text(encoding="utf-8"))
        return IssueRevision(
            issue_id=str(payload["issue_id"]),
            revision=int(payload["revision"]),
            category=IssueCategory(str(payload["category"])),
            phrase_text=str(payload["phrase_text"]),
            note=str(payload["note"]),
            seed=int(payload["seed"]),
            problem_word=payload.get("problem_word"),
            heard_as=payload.get("heard_as"),
            desired_pronunciation=payload.get("desired_pronunciation"),
            outcome=RetestOutcome(str(payload["outcome"])) if payload.get("outcome") else None,
            metadata=dict(payload.get("metadata", {})),
            created_at=str(payload.get("created_at", "")),
            status=str(payload.get("status", "OPEN")),
        )


def new_issue(*, category: IssueCategory, phrase_text: str, note: str, seed: int, **fields: object) -> IssueRevision:
    return IssueRevision(uuid4().hex, 1, category, phrase_text, note, seed, **fields)


def codex_request(issue: IssueRevision, evidence_path: Path | None = None) -> str:
    metadata = issue.metadata
    sentence = str(metadata.get("current_sentence") or issue.phrase_text)
    recent = metadata.get("recent_phrase_context") or [issue.phrase_text]
    reproduction = f"Launch scripts/luna_fast_speaker.py, use seed {issue.seed}, submit the exact source sentence, and retest the selected phrase."
    pronunciation = ""
    if issue.category is IssueCategory.PRONUNCIATION:
        pronunciation = f"\nProblem word: {issue.problem_word}\nHeard as: {issue.heard_as}\nDesired pronunciation: {issue.desired_pronunciation}\n"
    analysis = (
        "Use existing Luna prosody metrics and compare numerically with accepted examples; do not rely only on subjective guessing. Prefer a rule/class correction and do not promote it to production without approval."
        if issue.category is IssueCategory.INTONATION
        else "Distinguish a deterministic lexical defect, a context-sensitive split/phonetic defect, and one-off synthesis instability. Do not add a global respell without repeated evidence."
    )
    return f"""# Luna FAST Speaker issue request

Issue: {issue.issue_id} revision {issue.revision}
Status: {issue.status}
Category: {issue.category.value}
Source mode/session: {metadata.get('source_mode', 'unknown')} / {metadata.get('session_name', 'unknown')}
Exact source sentence: {sentence}
Selected phrase: {issue.phrase_text}
Phrase ID/class: {metadata.get('phrase_id', 'unknown')} / {metadata.get('phrase_class', 'unknown')}
Recent phrase context: {recent}
Seed: {issue.seed}
Listening note: {issue.note}{pronunciation}
Engine/config snapshot: Chatterbox Multilingual V3; Candidate B SHA-256 30C6D3405F46684AF467C7D26FF40A2FB57DD48CC84CD24CF7403D9AA00A2BB9; language_id=ko; exaggeration=0.5; cfg=0.5; temperature=0.72; repetition_penalty=1.2; min_p=0.05; top_p=1.0.
Code/rule revision: {metadata.get('code_revision', 'unknown')} / {metadata.get('rule_revision', 'unknown')}
Timing metrics: {metadata.get('metrics', {})}
Issue WAV: {evidence_path or 'same revision folder/original_phrase.wav'}

Reproduction: {reproduction}

Requested fix scope: change only the approved FAST-test rule/module needed for this defect. {analysis}

Required regression: reproduce with the recorded text and seed; add a focused deterministic test for any lexical/split correction; run FAST Speaker unit/regression checks and a real Luna retest. Report changed files and exact test results.

Invariants: use only Chatterbox Multilingual V3 + Candidate B. Do not change the reference, fixed parameters, production pipeline, frozen audio/cache, pins, or normal FAST behavior. Do not auto-promote experimental overlay rules to production.

Complete only this issue fix, write the changed-files and verification report, then stop for user review.
"""
