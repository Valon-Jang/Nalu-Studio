"""Restartable local named-pipe worker for in-memory FAST Speaker synthesis."""

from __future__ import annotations

import argparse
import base64
import importlib
from multiprocessing.connection import Client, Listener
from pathlib import Path
import subprocess
import threading
import time
from typing import Any, Callable, Mapping
from uuid import uuid4

from .contracts import FastBackend
from .fast_adapter import LunaFastBackend
from .ipc import WorkerCommand, error_response, ok_response
from .metrics import phrase_metrics
from .pcm import PcmFrame

BackendFactory = Callable[[Path], FastBackend]


def default_backend_factory(repo_root: Path) -> FastBackend:
    from scripts.luna_quality.voice_runtime.runtime import LunaVoiceRuntime

    return LunaFastBackend(LunaVoiceRuntime(repo_root))


def load_backend_factory(spec: str | None) -> BackendFactory:
    if not spec:
        return default_backend_factory
    module_name, separator, attribute = spec.partition(":")
    if not separator or not module_name or not attribute:
        raise ValueError("backend factory must be module:attribute")
    factory = getattr(importlib.import_module(module_name), attribute)
    if not callable(factory):
        raise ValueError("backend factory must be callable")
    return factory


class ResidentWorker:
    """Process-local backend with concurrent control and serial TTS calls."""

    def __init__(self, repo_root: Path, backend_factory: BackendFactory = default_backend_factory) -> None:
        self.repo_root = repo_root.resolve()
        self.backend = backend_factory(self.repo_root)
        self._synthesis_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._generation_by_session: dict[str, str] = {}
        self._shutdown = threading.Event()
        self.started_monotonic = time.perf_counter()
        self.ready: Mapping[str, Any] | None = None
        self.ready_monotonic: float | None = None

    def start(self) -> Mapping[str, Any]:
        if self.ready is None:
            self.ready = dict(self.backend.initialize_once())
            self.ready_monotonic = time.perf_counter()
        return self.ready

    def health(self) -> dict[str, Any]:
        ready = self.start()
        return {
            "worker_status": "ready",
            "worker_ready_seconds": round((self.ready_monotonic or time.perf_counter()) - self.started_monotonic, 6),
            "backend": dict(ready),
        }

    def invalidate(self, session_id: str, generation_id: str) -> dict[str, Any]:
        with self._state_lock:
            self._generation_by_session[session_id] = generation_id
        return {"session_id": session_id, "generation_id": generation_id, "invalidated": True}

    def synthesize(self, command: WorkerCommand) -> dict[str, Any]:
        assert command.phrase is not None and command.seed is not None
        assert command.session_id is not None and command.generation_id is not None
        self.start()
        with self._state_lock:
            self._generation_by_session.setdefault(command.session_id, command.generation_id)
        started = time.perf_counter()
        with self._synthesis_lock:
            result = self.backend.synthesize_fast_phrase(command.phrase, command.seed)
        finished = time.perf_counter()
        frame = PcmFrame(result.pcm_s16le, result.sample_rate)
        pcm_ready = time.perf_counter()
        metrics = phrase_metrics(
            worker_ready_seconds=(self.ready_monotonic or started) - self.started_monotonic,
            synthesis_started_monotonic=started,
            synthesis_finished_monotonic=finished,
            pcm_ready_monotonic=pcm_ready,
            frame=frame,
            generation_seconds=result.generation_seconds,
        )
        with self._state_lock:
            current_generation = self._generation_by_session.get(command.session_id)
        return {
            "session_id": command.session_id,
            "generation_id": command.generation_id,
            "stale": current_generation != command.generation_id,
            "phrase": {
                "phrase_id": result.phrase.phrase_id,
                "text": result.phrase.text,
                "sentence_final": result.phrase.sentence_final,
                "forced": result.phrase.forced,
            },
            "spoken_text": result.spoken_text,
            "seed": result.seed,
            "pcm": frame.to_mapping(),
            "metrics": metrics.to_mapping(),
            "metadata": dict(result.metadata),
        }

    def dispatch(self, command: WorkerCommand) -> dict[str, Any]:
        if command.command == "health":
            return self.health()
        if command.command == "invalidate":
            assert command.session_id is not None and command.generation_id is not None
            return self.invalidate(command.session_id, command.generation_id)
        if command.command == "synthesize":
            return self.synthesize(command)
        if command.command == "shutdown":
            self._shutdown.set()
            return {"worker_status": "stopping"}
        raise ValueError(f"unsupported command: {command.command}")


class WorkerPipeServer:
    """AF_PIPE server; each short connection carries one command."""

    def __init__(self, address: str, authkey: bytes, worker: ResidentWorker) -> None:
        self.address, self.authkey, self.worker = address, authkey, worker
        self._listener: Listener | None = None

    def serve_forever(self) -> None:
        self.worker.start()
        self._listener = Listener(self.address, family="AF_PIPE", authkey=self.authkey)
        try:
            while not self.worker._shutdown.is_set():
                try:
                    connection = self._listener.accept()
                except OSError:
                    if self.worker._shutdown.is_set():
                        break
                    raise
                threading.Thread(target=self._serve_connection, args=(connection,), daemon=True).start()
        finally:
            self._listener.close()

    def _serve_connection(self, connection: Any) -> None:
        request_id: str | None = None
        try:
            payload = connection.recv()
            if not isinstance(payload, Mapping):
                raise ValueError("worker payload must be a mapping")
            request_id = str(payload.get("request_id") or "") or None
            command = WorkerCommand.from_mapping(payload)
            connection.send(ok_response(command, **self.worker.dispatch(command)))
        except Exception as error:
            connection.send(error_response(request_id=request_id, message=f"{type(error).__name__}: {error}"))
        finally:
            connection.close()
            if self.worker._shutdown.is_set() and self._listener is not None:
                self._listener.close()


class WorkerClient:
    """Synchronous client for a future controller, never a UI thread."""

    def __init__(self, address: str, authkey: bytes) -> None:
        self.address, self.authkey = address, authkey

    def request(self, command: WorkerCommand, timeout_seconds: float = 30.0) -> Mapping[str, Any]:
        deadline, last_error = time.monotonic() + timeout_seconds, None
        while time.monotonic() < deadline:
            try:
                connection = Client(self.address, family="AF_PIPE", authkey=self.authkey)
                try:
                    connection.send(command.to_mapping())
                    response = connection.recv()
                finally:
                    connection.close()
                if not isinstance(response, Mapping):
                    raise RuntimeError("worker response must be a mapping")
                if response.get("status") != "ok":
                    raise RuntimeError(str(response.get("message", "worker command failed")))
                return response
            except (FileNotFoundError, ConnectionRefusedError, OSError) as error:
                last_error = error
                time.sleep(0.05)
        raise TimeoutError(f"worker pipe unavailable after {timeout_seconds}s: {last_error}")


class WorkerProcess:
    """Own an external canonical-Python worker and support restart."""

    def __init__(self, repo_root: Path, *, python_executable: Path | None = None, backend_factory_spec: str | None = None) -> None:
        self.repo_root = repo_root.resolve()
        self.python_executable = python_executable or self.repo_root / "engine" / "chatterbox-v3" / "venv" / "Scripts" / "python.exe"
        self.backend_factory_spec = backend_factory_spec
        self.address: str | None = None
        self.authkey: bytes | None = None
        self.process: subprocess.Popen[str] | None = None

    def start(self, timeout_seconds: float = 90.0) -> WorkerClient:
        if self.process is not None and self.process.poll() is None:
            return self.client()
        self.address, self.authkey = rf"\\.\pipe\luna-fast-speaker-{uuid4().hex}", uuid4().bytes
        args = [str(self.python_executable), "-X", "utf8", "-m", "scripts.luna_quality.fast_speaker.worker", "--pipe", self.address, "--authkey", base64.b64encode(self.authkey).decode("ascii"), "--repo-root", str(self.repo_root)]
        if self.backend_factory_spec:
            args.extend(["--backend-factory", self.backend_factory_spec])
        self.process = subprocess.Popen(args, cwd=self.repo_root, text=True)
        client = self.client()
        client.request(WorkerCommand("health", uuid4().hex), timeout_seconds)
        return client

    def client(self) -> WorkerClient:
        if not self.address or not self.authkey:
            raise RuntimeError("worker has not been started")
        return WorkerClient(self.address, self.authkey)

    def shutdown(self, timeout_seconds: float = 10.0) -> None:
        if self.process is None:
            return
        if self.process.poll() is None:
            try:
                self.client().request(WorkerCommand("shutdown", uuid4().hex), timeout_seconds)
            except (OSError, RuntimeError, TimeoutError):
                pass
            try:
                self.process.wait(timeout_seconds)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                self.process.wait(timeout_seconds)
        self.process = None

    def restart(self, timeout_seconds: float = 90.0) -> WorkerClient:
        self.shutdown()
        return self.start(timeout_seconds)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local FAST Speaker resident worker")
    parser.add_argument("--pipe", required=True)
    parser.add_argument("--authkey", required=True)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--backend-factory")
    args = parser.parse_args(argv)
    server = WorkerPipeServer(args.pipe, base64.b64decode(args.authkey.encode("ascii")), ResidentWorker(Path(args.repo_root), load_backend_factory(args.backend_factory)))
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
