"""Localhost-only newline-delimited JSON transport for the resident worker."""

from __future__ import annotations

import json
import socket
import socketserver
import threading
from typing import Any, Mapping

from .contract import RESPONSE_SCHEMA_VERSION


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 18765
MAX_REQUEST_BYTES = 1_000_000


class VoiceRequestHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        raw = self.rfile.readline(MAX_REQUEST_BYTES + 1)
        if len(raw) > MAX_REQUEST_BYTES:
            self._write({"schema_version": RESPONSE_SCHEMA_VERSION, "status": "error", "error": "request_too_large"})
            return
        try:
            payload = json.loads(raw.decode("utf-8"))
            action = str(payload.get("action", "synthesize")) if isinstance(payload, dict) else "synthesize"
            if action == "health":
                response = self.server.runtime.health()  # type: ignore[attr-defined]
            elif action == "shutdown":
                response = {"schema_version": RESPONSE_SCHEMA_VERSION, "status": "stopping", "local_only": True}
                threading.Thread(target=self.server.shutdown, daemon=True).start()
            elif action == "synthesize":
                response = self.server.runtime.handle(payload)  # type: ignore[attr-defined]
            else:
                raise ValueError("unsupported action")
        except Exception as error:
            response = {
                "schema_version": RESPONSE_SCHEMA_VERSION,
                "status": "error",
                "error_type": type(error).__name__,
                "error": str(error),
                "local_only": True,
            }
        self._write(response)

    def _write(self, payload: Mapping[str, Any]) -> None:
        self.wfile.write((json.dumps(dict(payload), ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"))


class LocalVoiceServer(socketserver.TCPServer):
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], runtime: Any) -> None:
        host, _ = address
        if host not in {"127.0.0.1", "localhost"}:
            raise ValueError("Luna Voice service is restricted to localhost")
        self.runtime = runtime
        super().__init__((DEFAULT_HOST, address[1]), VoiceRequestHandler)


def serve(runtime: Any, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    runtime.start()
    with LocalVoiceServer((host, port), runtime) as server:
        server.serve_forever(poll_interval=0.25)


def send_request(payload: Mapping[str, Any], host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, timeout: float = 600.0) -> dict[str, Any]:
    encoded = (json.dumps(dict(payload), ensure_ascii=False) + "\n").encode("utf-8")
    if len(encoded) > MAX_REQUEST_BYTES:
        raise ValueError("request exceeds transport limit")
    with socket.create_connection((host, port), timeout=timeout) as connection:
        connection.settimeout(timeout)
        connection.sendall(encoded)
        with connection.makefile("rb") as reader:
            line = reader.readline(MAX_REQUEST_BYTES + 1)
    if not line:
        raise ConnectionError("resident worker closed without a response")
    response = json.loads(line.decode("utf-8"))
    if not isinstance(response, dict):
        raise ValueError("resident worker returned a non-object response")
    return response
