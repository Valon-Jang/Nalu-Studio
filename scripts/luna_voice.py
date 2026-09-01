#!/usr/bin/env python3
"""One user-facing entry point: dialogue text in, Luna WAV out.

The first request starts the canonical production Python worker. The worker
keeps Chatterbox Multilingual V3 and Candidate B conditionals resident, so
later FAST requests generate one take without model/reference reloads.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Mapping
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_PYTHON = ROOT / "engine" / "chatterbox-v3" / "venv" / "Scripts" / "python.exe"
STATE_DIR = Path(os.environ.get("LOCALAPPDATA", ROOT / ".local")) / "Gongdaeluna" / "luna-voice"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "luna_voice"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.luna_quality.voice_runtime.contract import REQUEST_SCHEMA_VERSION, VoiceMode
from scripts.luna_quality.voice_runtime.runtime import LunaVoiceRuntime, _atomic_write_json
from scripts.luna_quality.voice_runtime.transport import DEFAULT_HOST, DEFAULT_PORT, send_request, serve


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    commands = {"serve", "start", "stop", "status", "synthesize", "request"}
    if raw_argv and raw_argv[0] not in commands and not raw_argv[0].startswith("-"):
        raw_argv.insert(0, "synthesize")

    parser = argparse.ArgumentParser(description="Dialogue text -> Candidate B Luna WAV")
    sub = parser.add_subparsers(dest="command", required=True)
    server = sub.add_parser("serve", help="run the resident localhost worker")
    server.add_argument("--host", default=DEFAULT_HOST)
    server.add_argument("--port", type=int, default=DEFAULT_PORT)
    start = sub.add_parser("start", help="start the resident worker in the background")
    start.add_argument("--port", type=int, default=DEFAULT_PORT)
    stop = sub.add_parser("stop", help="stop the resident worker")
    stop.add_argument("--port", type=int, default=DEFAULT_PORT)
    status = sub.add_parser("status", help="show worker status")
    status.add_argument("--port", type=int, default=DEFAULT_PORT)
    synth = sub.add_parser("synthesize", help="generate a Luna WAV from dialogue")
    synth.add_argument("text")
    synth.add_argument("--mode", choices=[mode.value for mode in VoiceMode], default=VoiceMode.FAST.value)
    synth.add_argument("--output")
    synth.add_argument("--response")
    synth.add_argument("--seed", type=int, default=20260823)
    synth.add_argument("--block-id", default="B01")
    synth.add_argument("--port", type=int, default=DEFAULT_PORT)
    synth.add_argument("--no-auto-start", action="store_true")
    request = sub.add_parser("request", help="send a versioned JSON request file")
    request.add_argument("--input", required=True)
    request.add_argument("--response")
    request.add_argument("--port", type=int, default=DEFAULT_PORT)
    request.add_argument("--no-auto-start", action="store_true")
    args = parser.parse_args(raw_argv)

    if args.command == "serve":
        _require_production_python()
        runtime = LunaVoiceRuntime(ROOT)
        serve(runtime, host=args.host, port=args.port)
        return 0
    if args.command == "start":
        result = ensure_worker(args.port)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    if args.command == "stop":
        try:
            result = send_request({"action": "shutdown"}, port=args.port, timeout=10)
        except OSError:
            result = {"status": "not_running", "local_only": True}
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    if args.command == "status":
        try:
            result = send_request({"action": "health"}, port=args.port, timeout=5)
        except OSError as error:
            result = {"status": "not_running", "error": type(error).__name__, "local_only": True}
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result.get("status") == "ready" else 1
    if args.command == "synthesize":
        request_id = uuid4().hex
        output = Path(args.output).resolve() if args.output else _default_output(request_id)
        response_path = Path(args.response).resolve() if args.response else output.with_suffix(".json")
        payload = {
            "schema_version": REQUEST_SCHEMA_VERSION,
            "request_id": request_id,
            "mode": args.mode,
            "text": args.text,
            "output_wav": str(output),
            "output_json": str(response_path),
            "seed": args.seed,
            "block_id": args.block_id,
        }
        result = _dispatch(payload, args.port, auto_start=not args.no_auto_start)
        _atomic_write_json(response_path, result)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result.get("status") == "ok" else 1
    if args.command == "request":
        input_path = Path(args.input).resolve()
        payload = json.loads(input_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            parser.error("request file must contain a JSON object")
        result = _dispatch(payload, args.port, auto_start=not args.no_auto_start)
        response_path = Path(args.response).resolve() if args.response else None
        if response_path is not None:
            _atomic_write_json(response_path, result)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result.get("status") == "ok" else 1
    raise AssertionError("unreachable")


def ensure_worker(port: int = DEFAULT_PORT, timeout: float = 120.0) -> dict[str, Any]:
    try:
        current = send_request({"action": "health"}, port=port, timeout=2)
        if current.get("status") == "ready":
            return current
    except OSError:
        pass
    if not PRODUCTION_PYTHON.is_file():
        raise FileNotFoundError(f"canonical production Python not found: {PRODUCTION_PYTHON}")
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    stdout_path = STATE_DIR / "worker.stdout.log"
    stderr_path = STATE_DIR / "worker.stderr.log"
    creationflags = 0
    kwargs: dict[str, Any] = {}
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW
    else:
        kwargs["start_new_session"] = True
    with stdout_path.open("ab") as stdout, stderr_path.open("ab") as stderr:
        process = subprocess.Popen(
            [str(PRODUCTION_PYTHON), str(Path(__file__).resolve()), "serve", "--port", str(port)],
            cwd=str(ROOT),
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            creationflags=creationflags,
            **kwargs,
        )
    (STATE_DIR / "worker.pid").write_text(str(process.pid), encoding="ascii")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"resident worker exited during startup; see {stderr_path}")
        try:
            result = send_request({"action": "health"}, port=port, timeout=2)
            if result.get("status") == "ready":
                return result
        except OSError:
            time.sleep(0.25)
    raise TimeoutError(f"resident worker did not become ready within {timeout:.0f}s; see {stderr_path}")


def _dispatch(payload: Mapping[str, Any], port: int, *, auto_start: bool) -> dict[str, Any]:
    if auto_start:
        ensure_worker(port)
    return send_request(payload, port=port)


def _default_output(request_id: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return (DEFAULT_OUTPUT_DIR / f"{stamp}_{request_id[:8]}_luna.wav").resolve()


def _require_production_python() -> None:
    if Path(sys.executable).resolve() != PRODUCTION_PYTHON.resolve():
        raise RuntimeError(f"serve must run with canonical production Python: {PRODUCTION_PYTHON}")


if __name__ == "__main__":
    raise SystemExit(main())
