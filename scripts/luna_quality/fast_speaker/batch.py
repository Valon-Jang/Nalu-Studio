"""S04 newline-first batch parsing and resumable sentence state."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Any, Mapping


SESSION_SCHEMA_VERSION = "luna-fast-speaker-session/2"
LEGACY_SESSION_SCHEMA_VERSION = "luna-fast-speaker-session/1"
_SENTENCE_END = re.compile(r"(?<=[.!?。！？])\s+")


class BatchState(str, Enum):
    PENDING = "PENDING"
    PLAYING = "PLAYING"
    PASS = "PASS"
    ISSUE = "ISSUE"
    PAUSED = "PAUSED"
    RETEST_PENDING = "RETEST_PENDING"


@dataclass
class BatchItem:
    item_id: str
    text: str
    state: BatchState = BatchState.PENDING

    def to_mapping(self) -> dict[str, str]:
        return {"item_id": self.item_id, "text": self.text, "state": self.state.value}


def parse_batch_text(text: str) -> list[str]:
    """Keep non-empty source-line order, splitting punctuation only within a line."""
    result: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        result.extend(part.strip() for part in _SENTENCE_END.split(line) if part.strip())
    return result


class BatchSession:
    def __init__(
        self,
        name: str,
        items: list[BatchItem],
        *,
        recovered: bool = False,
        source_text: str = "",
        source_path: str | None = None,
        issue_links: list[str] | None = None,
        code_revision: str | None = None,
    ) -> None:
        if not name.strip() or not items:
            raise ValueError("session name and at least one batch item are required")
        self.name, self.items, self.recovered = name.strip(), items, recovered
        self.source_text = source_text or "\n".join(item.text for item in items)
        self.source_path = source_path
        self.issue_links = list(issue_links or [])
        self.code_revision = code_revision
        self.app_version = "luna-fast-speaker-v1"
        self.mode = "batch"
        self.paused = False
        self.active_index: int | None = None

    @classmethod
    def from_text(cls, name: str, text: str, *, source_path: str | None = None, code_revision: str | None = None) -> "BatchSession":
        return cls(
            name,
            [BatchItem(f"S{index:04d}", value) for index, value in enumerate(parse_batch_text(text), 1)],
            source_text=text,
            source_path=source_path,
            code_revision=code_revision,
        )

    def start_next(self) -> BatchItem | None:
        if self.paused:
            return None
        for index, item in enumerate(self.items):
            if item.state in {BatchState.PENDING, BatchState.RETEST_PENDING}:
                self.active_index = index
                item.state = BatchState.PLAYING
                return item
        self.active_index = None
        return None

    def complete_active_cleanly(self) -> None:
        if self.paused or self.active_index is None:
            return
        item = self.items[self.active_index]
        if item.state is BatchState.PLAYING:
            item.state = BatchState.PASS
        self.active_index = None

    def pause(self) -> None:
        self.paused = True

    def continue_session(self) -> None:
        self.paused = False

    def mark_active_issue(self) -> BatchItem | None:
        if self.active_index is not None:
            item = self.items[self.active_index]
            item.state = BatchState.ISSUE
            self.active_index = None
            return item
        return None

    def recover_interrupted_active(self) -> None:
        """Make an interrupted sentence safe to replay from its beginning."""
        if self.active_index is not None and self.items[self.active_index].state is BatchState.PLAYING:
            self.items[self.active_index].state = BatchState.PENDING
        self.active_index = None

    def resume_from_sentence(self, text: str) -> BatchItem:
        """Resume context validation from the exact sentence that had an issue."""
        for index, item in enumerate(self.items):
            if item.text == text:
                self.active_index = None
                self.paused = False
                item.state = BatchState.PENDING
                return item
        raise ValueError("issue sentence is not present in this batch session")

    def counts(self) -> Mapping[str, int]:
        return {state.value: sum(item.state is state for item in self.items) for state in BatchState}

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": SESSION_SCHEMA_VERSION,
            "app_version": self.app_version,
            "name": self.name,
            "mode": self.mode,
            "source_text": self.source_text,
            "source_path": self.source_path,
            "paused": self.paused,
            "active_index": self.active_index,
            "current_sentence_index": self.active_index,
            "issue_links": list(self.issue_links),
            "counts": dict(self.counts()),
            "code_revision": self.code_revision,
            "items": [item.to_mapping() for item in self.items],
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "BatchSession":
        if value.get("schema_version") not in {SESSION_SCHEMA_VERSION, LEGACY_SESSION_SCHEMA_VERSION}:
            raise ValueError("unsupported session schema")
        items = [BatchItem(str(item["item_id"]), str(item["text"]), BatchState(str(item["state"]))) for item in value["items"]]
        session = cls(
            str(value["name"]),
            items,
            recovered=True,
            source_text=str(value.get("source_text") or ""),
            source_path=str(value["source_path"]) if value.get("source_path") else None,
            issue_links=[str(item) for item in value.get("issue_links", [])],
            code_revision=str(value["code_revision"]) if value.get("code_revision") else None,
        )
        active = value.get("active_index")
        session.active_index = active if isinstance(active, int) and 0 <= active < len(items) else None
        session.recover_interrupted_active()
        session.paused = bool(value.get("paused", False))
        return session
