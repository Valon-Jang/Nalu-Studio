"""Versioned request contract shared by FAST and PRODUCTION synthesis."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4


REQUEST_SCHEMA_VERSION = "luna-voice-request/1"
RESPONSE_SCHEMA_VERSION = "luna-voice-response/1"
DEFAULT_SEED = 20260823


class VoiceMode(str, Enum):
    FAST = "fast"
    PRODUCTION = "production"


@dataclass(frozen=True)
class VoiceRequest:
    request_id: str
    text: str
    output_wav: Path
    output_json: Path | None = None
    mode: VoiceMode = VoiceMode.FAST
    seed: int = DEFAULT_SEED
    block_id: str = "B01"
    production_outdir: Path | None = None
    schema_version: str = REQUEST_SCHEMA_VERSION

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "VoiceRequest":
        if not isinstance(value, Mapping):
            raise ValueError("request must be a JSON object")
        schema = str(value.get("schema_version", REQUEST_SCHEMA_VERSION))
        if schema != REQUEST_SCHEMA_VERSION:
            raise ValueError(f"unsupported request schema: {schema}")
        text = str(value.get("text", "")).strip()
        if not text:
            raise ValueError("text is required")
        if len(text) > 2000:
            raise ValueError("text exceeds the 2000-character request limit")
        output = str(value.get("output_wav", "")).strip()
        if not output:
            raise ValueError("output_wav is required")
        try:
            mode = VoiceMode(str(value.get("mode", VoiceMode.FAST.value)).strip().lower())
        except ValueError as error:
            raise ValueError("mode must be 'fast' or 'production'") from error
        try:
            seed = int(value.get("seed", DEFAULT_SEED))
        except (TypeError, ValueError) as error:
            raise ValueError("seed must be an integer") from error
        if not 0 <= seed < 2**31:
            raise ValueError("seed must be in [0, 2^31)")
        request_id = str(value.get("request_id") or uuid4().hex).strip()
        if not request_id or len(request_id) > 128:
            raise ValueError("request_id must contain 1..128 characters")
        block_id = str(value.get("block_id", "B01")).strip()
        if not block_id or len(block_id) > 64 or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for char in block_id):
            raise ValueError("block_id may contain only letters, digits, '_' and '-'")
        output_json = str(value.get("output_json", "")).strip() or None
        production_outdir = str(value.get("production_outdir", "")).strip() or None
        return cls(
            request_id=request_id,
            text=text,
            output_wav=Path(output),
            output_json=Path(output_json) if output_json else None,
            mode=mode,
            seed=seed,
            block_id=block_id,
            production_outdir=Path(production_outdir) if production_outdir else None,
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "mode": self.mode.value,
            "text": self.text,
            "output_wav": str(self.output_wav),
            "seed": self.seed,
            "block_id": self.block_id,
        }
        if self.output_json is not None:
            payload["output_json"] = str(self.output_json)
        if self.production_outdir is not None:
            payload["production_outdir"] = str(self.production_outdir)
        return payload
