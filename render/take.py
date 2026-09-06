"""Guard: the presenter take must be long enough for the timeline.

Why this exists
---------------
``scene_layout`` cuts scenes from a *continuous* recording, advancing a take
cursor by each scene's duration. Nothing checked that the recording actually
contains those frames. When it does not, MLT clamps to the end of the source:
the render ends early, the final scene is truncated, and the exit status is
zero.

That was measured on the demo production -- the document asked for frame 359 of
a 353-frame take and the master silently lost 7 frames. The failure scales: a
take five seconds short loses five seconds of the final scene, still
"successfully".

It is deliberately checked **before** mlt-melt runs. Truncation is invisible
afterwards, because the output's frame count is wrong-but-plausible and matches
neither the document nor anything else worth comparing against.

``TakeTooShortError`` subclasses ``DocumentError`` (itself a ``ValueError``), so
every existing ``except DocumentError`` path -- the render CLI, the MCP tools --
reports it correctly without modification.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from core.document import DocumentError
from render.mlt_xml import scene_layout


class TakeTooShortError(DocumentError):
    """The presenter recording is shorter than the timeline cut from it."""


def presenter_frames(path: str | Path) -> int:
    """Return the video frame count of *path*.

    ``nb_frames`` is a container hint and is absent or wrong often enough to be
    untrustworthy here, so frames are counted for real with ``-count_frames``.
    Takes are single-digit minutes at most, so the extra decode is cheap next to
    a render -- and this check only pays off if it is accurate.
    """
    source = Path(path)
    if not source.is_file():
        raise OSError(f"presenter take not found: {source}")
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
         "-show_entries", "stream=nb_read_frames", "-of", "json", str(source)],
        capture_output=True, text=True, check=False)
    if probe.returncode != 0:
        raise OSError(f"could not probe presenter take {source}: {probe.stderr.strip()}")
    try:
        streams = json.loads(probe.stdout)["streams"]
        return int(streams[0]["nb_read_frames"])
    except (KeyError, IndexError, ValueError, TypeError) as exc:
        raise OSError(
            f"presenter take {source} has no readable video stream"
        ) from exc


def required_take_frames(document: dict[str, Any]) -> tuple[int, str]:
    """Frames the timeline consumes from the take, and the last scene's id.

    Take time, **not** programme time: a transition overlaps two scenes'
    positions in the output, but each scene is still cut from its own stretch of
    the recording. Measuring the programme would wrongly pass a short take
    whenever transitions were used.
    """
    layout = scene_layout(document)
    if not layout:
        return 0, ""
    fps = float(document["target"]["fps"])
    # take_start already accumulates every preceding scene's duration.
    last = max(layout, key=lambda item: item["take_start"] + item["duration"])
    return round((last["take_start"] + last["duration"]) * fps), last["id"]


def validate_take_length(document: dict[str, Any], root: str | Path) -> bool:
    """Raise ``TakeTooShortError`` if the take cannot supply the timeline.

    Returns True when the take is long enough. A missing or unprobeable take
    raises ``OSError`` -- rendering could not have worked anyway, and the render
    CLI already reports OSError.
    """
    required, scene_id = required_take_frames(document)
    if not required:
        return True
    source = Path(root) / document["presenter"]["source"]
    available = presenter_frames(source)
    # One frame of tolerance, matching the board duration guard: encoders land a
    # frame either side of a requested duration, and rejecting an exact fit
    # would fail correct documents.
    if available >= required - 1:
        return True
    fps = float(document["target"]["fps"])
    shortfall = (required - available) / fps
    raise TakeTooShortError(
        f"presenter take is too short for the timeline: scene {scene_id!r} needs "
        f"take frame {required} but {source.name} has {available} "
        f"({shortfall:.2f}s short at {fps:g}fps). MLT would silently truncate "
        f"the final scene. Re-run `impromptu reconcile` against this take so "
        f"measured_sec matches what was actually recorded, or record a longer take."
    )


__all__ = [
    "TakeTooShortError",
    "presenter_frames",
    "required_take_frames",
    "validate_take_length",
]
