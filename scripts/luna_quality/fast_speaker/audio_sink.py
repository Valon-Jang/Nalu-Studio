"""In-memory Windows PCM output and a deterministic sink for controller tests."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import threading
from typing import Callable, Protocol

from .pcm import PcmFrame


class AudioSink(Protocol):
    def play(self, frame: PcmFrame, on_started: Callable[[], None], on_finished: Callable[[], None]) -> None: ...
    def stop(self) -> None: ...
    def close(self) -> None: ...


class WinmmAudioSink:
    """Persistent Windows-default waveOut stream accepting PCM directly from RAM."""

    WAVE_MAPPER = 0xFFFFFFFF
    CALLBACK_EVENT = 0x00050000
    WHDR_DONE = 0x00000001

    class WAVEFORMATEX(ctypes.Structure):
        _fields_ = [("wFormatTag", wintypes.WORD), ("nChannels", wintypes.WORD), ("nSamplesPerSec", wintypes.DWORD), ("nAvgBytesPerSec", wintypes.DWORD), ("nBlockAlign", wintypes.WORD), ("wBitsPerSample", wintypes.WORD), ("cbSize", wintypes.WORD)]

    class WAVEHDR(ctypes.Structure):
        _fields_ = [("lpData", ctypes.c_char_p), ("dwBufferLength", wintypes.DWORD), ("dwBytesRecorded", wintypes.DWORD), ("dwUser", ctypes.c_void_p), ("dwFlags", wintypes.DWORD), ("dwLoops", wintypes.DWORD), ("lpNext", ctypes.c_void_p), ("reserved", ctypes.c_void_p)]

    def __init__(self) -> None:
        if not hasattr(ctypes, "windll"):
            raise RuntimeError("WinmmAudioSink requires Windows")
        self._winmm = ctypes.windll.winmm
        self._kernel32 = ctypes.windll.kernel32
        self._handle = ctypes.c_void_p()
        self._event = self._kernel32.CreateEventW(None, False, False, None)
        if not self._event:
            raise OSError("CreateEventW failed")
        self._format: tuple[int, int] | None = None
        self._lock = threading.RLock()
        self._active: tuple[ctypes.Array[ctypes.c_char], WinmmAudioSink.WAVEHDR] | None = None
        self._closed = False

    def _ensure_open(self, frame: PcmFrame) -> None:
        signature = (frame.sample_rate, frame.channels)
        if self._format == signature:
            return
        if self._format is not None:
            raise ValueError("persistent audio stream format cannot change")
        fmt = self.WAVEFORMATEX(1, frame.channels, frame.sample_rate, frame.sample_rate * frame.channels * 2, frame.channels * 2, 16, 0)
        result = self._winmm.waveOutOpen(ctypes.byref(self._handle), self.WAVE_MAPPER, ctypes.byref(fmt), self._event, 0, self.CALLBACK_EVENT)
        if result != 0:
            raise OSError(f"waveOutOpen failed: {result}")
        self._format = signature

    def play(self, frame: PcmFrame, on_started: Callable[[], None], on_finished: Callable[[], None]) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("audio sink is closed")
            if self._active is not None:
                raise RuntimeError("audio sink already has an active frame")
            self._ensure_open(frame)
            buffer = ctypes.create_string_buffer(frame.pcm_s16le)
            header = self.WAVEHDR(ctypes.cast(buffer, ctypes.c_char_p), len(frame.pcm_s16le), 0, None, 0, 0, None, None)
            result = self._winmm.waveOutPrepareHeader(self._handle, ctypes.byref(header), ctypes.sizeof(header))
            if result != 0:
                raise OSError(f"waveOutPrepareHeader failed: {result}")
            self._active = (buffer, header)
            on_started()
            result = self._winmm.waveOutWrite(self._handle, ctypes.byref(header), ctypes.sizeof(header))
            if result != 0:
                self._active = None
                raise OSError(f"waveOutWrite failed: {result}")
        threading.Thread(target=self._wait_finished, args=(on_finished,), daemon=True).start()

    def _wait_finished(self, on_finished: Callable[[], None]) -> None:
        self._kernel32.WaitForSingleObject(self._event, 0xFFFFFFFF)
        with self._lock:
            active = self._active
            self._active = None
            if active is not None and self._handle:
                self._winmm.waveOutUnprepareHeader(self._handle, ctypes.byref(active[1]), ctypes.sizeof(active[1]))
        on_finished()

    def stop(self) -> None:
        with self._lock:
            if self._handle:
                self._winmm.waveOutReset(self._handle)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self.stop()
            if self._handle:
                self._winmm.waveOutClose(self._handle)
            self._kernel32.CloseHandle(self._event)
            self._closed = True


class FakeAudioSink:
    """Manual-completion RAM-only audio sink for deterministic controller tests."""

    def __init__(self) -> None:
        self.frames: list[PcmFrame] = []
        self._finish: Callable[[], None] | None = None
        self.stopped = False

    def play(self, frame: PcmFrame, on_started: Callable[[], None], on_finished: Callable[[], None]) -> None:
        self.frames.append(frame)
        self.stopped = False
        self._finish = on_finished
        on_started()

    def finish(self) -> None:
        if self._finish is not None:
            callback, self._finish = self._finish, None
            callback()

    def stop(self) -> None:
        self.stopped = True
        self._finish = None

    def close(self) -> None:
        self.stop()
