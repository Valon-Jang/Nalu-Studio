"""Launch the local Luna FAST Speaker v1 Tkinter app."""

from __future__ import annotations

from pathlib import Path

from scripts.luna_quality.fast_speaker.ui import run


if __name__ == "__main__":
    run(Path(__file__).resolve().parents[1])
