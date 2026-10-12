"""Bounded command capture with process-group cleanup on POSIX."""

from __future__ import annotations

import os
import selectors
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

MAX_OUTPUT_BYTES = 65536


@dataclass(frozen=True)
class CapturedProcess:
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool
    stdout_truncated: bool
    stderr_truncated: bool


def capture_command(command: str, cwd: Path, timeout_seconds: float) -> CapturedProcess:
    if timeout_seconds <= 0:
        raise ValueError("command timeout must be positive")
    started = time.monotonic()
    process = subprocess.Popen(
        command, cwd=cwd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        start_new_session=os.name == "posix",
    )
    assert process.stdout is not None and process.stderr is not None
    captured = {"stdout": bytearray(), "stderr": bytearray()}
    truncated = {"stdout": False, "stderr": False}
    timed_out = False
    selector = selectors.DefaultSelector()
    for name, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
        os.set_blocking(stream.fileno(), False)
        selector.register(stream, selectors.EVENT_READ, name)
    cleanup_at: float | None = None
    try:
        while selector.get_map():
            now = time.monotonic()
            if cleanup_at is None and now - started >= timeout_seconds:
                timed_out = True
                _kill_group(process)
                cleanup_at = now
            elif cleanup_at is None and process.poll() is not None:
                # A shell may exit while a background descendant keeps its pipes open.
                _kill_group(process)
                cleanup_at = now
            if cleanup_at is not None and now - cleanup_at >= 0.5:
                break  # Even a descendant that escaped its group cannot hang capture.
            for key, _ in selector.select(timeout=0.05):
                chunk = os.read(key.fileobj.fileno(), 8192)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                name = key.data
                available = max(0, MAX_OUTPUT_BYTES - len(captured[name]))
                captured[name].extend(chunk[:available])
                truncated[name] |= len(chunk) > available
        remaining = max(0, timeout_seconds - (time.monotonic() - started))
        try:
            process.wait(timeout=remaining if cleanup_at is None else 1)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_group(process)
            process.wait(timeout=1)
    finally:
        _kill_group(process)
        process.wait(timeout=1)
        selector.close()
        process.stdout.close()
        process.stderr.close()
    stdout, stdout_clipped = _bounded_text(captured["stdout"])
    stderr, stderr_clipped = _bounded_text(captured["stderr"])
    return CapturedProcess(
        exit_code=124 if timed_out else process.returncode,
        stdout=stdout, stderr=stderr,
        duration_seconds=round(time.monotonic() - started, 3), timed_out=timed_out,
        stdout_truncated=truncated["stdout"] or stdout_clipped,
        stderr_truncated=truncated["stderr"] or stderr_clipped,
    )


def _bounded_text(value: bytearray) -> tuple[str, bool]:
    # Replacement characters can expand malformed UTF-8; retain the byte budget.
    encoded = value.decode("utf-8", errors="replace").encode()
    return (encoded[:MAX_OUTPUT_BYTES].decode("utf-8", errors="ignore"),
            len(encoded) > MAX_OUTPUT_BYTES)


def _kill_group(process: subprocess.Popen[bytes]) -> None:
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        elif process.poll() is None:
            process.kill()
    except ProcessLookupError:
        pass
