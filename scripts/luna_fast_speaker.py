"""Launch the local Luna FAST Speaker v1 Tkinter app."""

from __future__ import annotations

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.luna_quality.fast_speaker.ui import run


if __name__ == "__main__":
    run(REPO_ROOT)
