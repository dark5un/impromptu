"""Run mlt-melt deterministically and parse progress."""
from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from pathlib import Path


class MeltError(RuntimeError):
    """Raised when mlt-melt fails."""


def melt_command(project: str | Path, output: str | Path, *, threads: int = 1) -> list[str]:
    return ["mlt-melt", str(project), "real_time=-1", f"threads={threads}", "-consumer", f"avformat:{output}"]


def parse_progress(line: str) -> float | None:
    match = re.search(r"(?:position|frame)\s*[=:]\s*(\d+)", line, re.IGNORECASE)
    return float(match.group(1)) if match else None


def run_melt(project: str | Path, output: str | Path, *, threads: int = 1,
             on_progress: Callable[[float], None] | None = None) -> subprocess.CompletedProcess[str]:
    command = melt_command(project, output, threads=threads)
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, bufsize=1)
    lines: list[str] = []
    assert process.stdout is not None
    for line in process.stdout:
        lines.append(line)
        if on_progress:
            progress = parse_progress(line)
            if progress is not None:
                on_progress(progress)
    returncode = process.wait()
    result = subprocess.CompletedProcess(command, returncode, "".join(lines), "")
    if returncode:
        raise MeltError(f"mlt-melt failed ({returncode}):\n{result.stdout[-2000:]}")
    return result


__all__ = ["MeltError", "melt_command", "parse_progress", "run_melt"]
                                                          
