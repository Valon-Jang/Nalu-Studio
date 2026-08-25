"""Atomic local session persistence; audio is never persisted."""

from __future__ import annotations

import json
import os
from pathlib import Path

from .batch import BatchSession


class SessionStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def save(self, session: BatchSession) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        destination = self.root / f"{session.name}.json"
        temporary = destination.with_name(f".{destination.name}.tmp-{os.getpid()}")
        try:
            temporary.write_text(json.dumps(session.to_mapping(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        return destination

    def load(self, path: Path) -> BatchSession:
        return BatchSession.from_mapping(json.loads(path.read_text(encoding="utf-8")))
