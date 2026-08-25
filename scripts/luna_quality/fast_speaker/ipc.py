"""Versioned local-only command validation for the FAST Speaker pipe."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping
from uuid import uuid4

from .contracts import FastPhrase


WORKER_IPC_SCHEMA_VERSION = "luna-fast-speaker-ipc/1"
COMMANDS = frozenset({"health", "synthesize", "invalidate", "shutdown"})


@dataclass(frozen=True)
class WorkerCommand:
    command: str
    request_id: str
    session_id: str | None = None
    generation_id: str | None = None
    phrase: FastPhrase | None = None
    seed: int | None = None
    schema_version: str = WORKER_IPC_SCHEMA_VERSION

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "WorkerCommand":
        if str(value.get("schema_version", WORKER_IPC_SCHEMA_VERSION)) != WORKER_IPC_SCHEMA_VERSION:
            raise ValueError("unsupported worker IPC schema")
        command = str(value.get("command", "")).strip().lower()
        if command not in COMMANDS:
            raise ValueError(f"unsupported worker command: {command}")
        request_id = str(value.get("request_id") or uuid4().hex).strip()
        if not request_id:
            raise ValueError("request_id is required")
        session_id = str(value.get("session_id", "")).strip() or None
        generation_id = str(value.get("generation_id", "")).strip() or None
        if command in {"synthesize", "invalidate"} and (not session_id or not generation_id):
            raise ValueError(f"{command} requires session_id and generation_id")
        phrase = None
        seed = None
        if command == "synthesize":
            phrase_value = value.get("phrase")
            if not isinstance(phrase_value, Mapping):
                raise ValueError("synthesize requires phrase")
            phrase = FastPhrase(
                phrase_id=str(phrase_value.get("phrase_id", "")),
                text=str(phrase_value.get("text", "")),
                sentence_final=bool(phrase_value.get("sentence_final", False)),
                forced=bool(phrase_value.get("forced", False)),
            )
            try:
                seed = int(value.get("seed"))
            except (TypeError, ValueError) as error:
                raise ValueError("synthesize requires integer seed") from error
            if not 0 <= seed < 2**31:
                raise ValueError("seed must be in [0, 2^31)")
        return cls(command, request_id, session_id, generation_id, phrase, seed)

    def to_mapping(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "command": self.command,
            "request_id": self.request_id,
        }
        if self.session_id is not None:
            payload["session_id"] = self.session_id
        if self.generation_id is not None:
            payload["generation_id"] = self.generation_id
        if self.phrase is not None:
            payload["phrase"] = {
                "phrase_id": self.phrase.phrase_id,
                "text": self.phrase.text,
                "sentence_final": self.phrase.sentence_final,
                "forced": self.phrase.forced,
            }
        if self.seed is not None:
            payload["seed"] = self.seed
        return payload


def ok_response(command: WorkerCommand, **payload: Any) -> dict[str, Any]:
    return {
        "schema_version": WORKER_IPC_SCHEMA_VERSION,
        "status": "ok",
        "request_id": command.request_id,
        "command": command.command,
        **payload,
    }


def error_response(*, request_id: str | None, message: str) -> dict[str, Any]:
    return {
        "schema_version": WORKER_IPC_SCHEMA_VERSION,
        "status": "error",
        "request_id": request_id,
        "message": message,
    }
