"""Run mlt-melt deterministically and parse progress.

Encoder choice is explicit here for a reason.  MLT's ``avformat`` consumer
defaults to **mpeg4 Simple Profile** when no ``vcodec`` is given, which
produced visibly blocky 1080p output at ~1.5 Mbps — a real defect spotted by
watching the file, not by any assertion on frame counts or duration.
"""
from __future__ import annotations

import functools
import re
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

# CRF 18 is visually transparent for screen-recorded and graphic content.
X264_CRF = 18
# libopenh264 has no CRF mode, so quality has to be a bitrate. 12 Mbps is
# generous for 1080p30 talking-head plus motion graphics.
OPENH264_BITRATE = "12M"
AUDIO_BITRATE = "192k"
CHROMA = {"420": "yuv420p", "444": "yuv444p"}


class MeltError(RuntimeError):
    """Raised when mlt-melt fails."""


@functools.cache
def _encoder_available(name: str) -> bool:
    """Whether the local ffmpeg exposes *name* as an encoder."""
    if shutil.which("ffmpeg") is None:
        return False
    probe = subprocess.run(["ffmpeg", "-hide_banner", "-h", f"encoder={name}"],
                           capture_output=True, text=True, check=False)
    return probe.returncode == 0 and "is not recognized" not in probe.stdout


def h264_encoder() -> str:
    """Return the best available H.264 encoder.

    ``libx264`` is preferred for its CRF mode.  Fedora's ``ffmpeg-free`` build
    ships without it, so ``libopenh264`` is the documented fallback (see
    docs/decisions.md).
    """
    for candidate in ("libx264", "libopenh264"):
        if _encoder_available(candidate):
            return candidate
    raise MeltError(
        "no H.264 encoder available: install ffmpeg with libx264 (RPM Fusion) "
        "or libopenh264. Fedora's ffmpeg-free has no libx264."
    )


def melt_command(project: str | Path, output: str | Path, *, threads: int = 1,
                 chroma: str = "420") -> list[str]:
    """Build the deterministic mlt-melt argv for an H.264 deliverable.

    ``chroma`` defaults to 4:2:0 (``yuv420p``) for maximum player/platform
    compatibility.  ``444`` requests 4:4:4 (``yuv444p``), which x264 encodes as
    High 4:4:4 Predictive -- sharper on saturated thin text, but rejected by
    some players, so it is opt-in only and requires libx264 (libopenh264 cannot
    encode 4:4:4 and errors rather than silently degrading).
    """
    if chroma not in CHROMA:
        raise ValueError(f"chroma must be one of {sorted(CHROMA)}, not {chroma!r}")
    encoder = h264_encoder()
    if chroma == "444" and encoder == "libopenh264":
        raise MeltError(
            "chroma 444 requires the libx264 encoder (High 4:4:4 Predictive); "
            "libopenh264 cannot encode 4:4:4. Install ffmpeg with libx264 "
            "(RPM Fusion) or drop --chroma 444."
        )
    command = [
        "mlt-melt", str(project),
        # Default realtime scheduling drops and duplicates frames, making the
        # render nondeterministic.
        "real_time=-1",
        f"threads={threads}",
        "-consumer", f"avformat:{output}",
        f"vcodec={encoder}",
        "acodec=aac",
        f"ab={AUDIO_BITRATE}",
        "ar=48000",
        f"pix_fmt={CHROMA[chroma]}",
        "movflags=+faststart",
    ]
    if encoder == "libx264":
        command += [f"crf={X264_CRF}", "preset=medium"]
    else:
        command.append(f"vb={OPENH264_BITRATE}")
    return command


def parse_progress(line: str) -> float | None:
    match = re.search(r"(?:position|frame)\s*[=:]\s*(\d+)", line, re.IGNORECASE)
    return float(match.group(1)) if match else None


def run_melt(project: str | Path, output: str | Path, *, threads: int = 1,
             chroma: str = "420",
             on_progress: Callable[[float], None] | None = None) -> subprocess.CompletedProcess[str]:
    command = melt_command(project, output, threads=threads, chroma=chroma)
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


__all__ = [
    "AUDIO_BITRATE",
    "OPENH264_BITRATE",
    "X264_CRF",
    "MeltError",
    "h264_encoder",
    "melt_command",
    "parse_progress",
    "run_melt",
]
