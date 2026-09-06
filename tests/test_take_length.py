"""The presenter take must be long enough for the timeline it is cut into.

Regression: `scene_layout` lays scenes end to end against a *continuous* take
(`take_cursor += duration`), so a document can ask for frames the recording
does not have. MLT clamps to the end of the source, the render ends early, and
the exit status is zero -- the demo master silently lost 7 frames off its final
scene.

This is the same blind-spot class as the board alpha bug: the output's frame
count is wrong-but-plausible, so no structural assertion catches it. These
tests therefore assert on the *error*, not on frame counts.

See docs/open-bug-take-shorter-than-timeline.md.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from core.document import DocumentError
from render.pipeline import render_production
from render.take import TakeTooShortError, presenter_frames, validate_take_length

_FFMPEG = shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(not _FFMPEG, reason="requires ffmpeg")
# Narrowed for the type checker; every use is behind needs_ffmpeg.
FFMPEG = _FFMPEG or "ffmpeg"


def _document(measured: list[float], fps: int = 30) -> dict:
    """A document whose scenes are hard cuts, so take time == programme time."""
    return {
        "schema": 1,
        "title": "Take length",
        "target": {"orientation": "landscape", "resolution": [1920, 1080], "fps": fps},
        "media": {},
        "presenter": {"source": "takes/take.mp4"},
        "scenes": [
            {
                "id": f"scene-{index}",
                "say": "words",
                "planned_sec": duration,
                "measured_sec": duration,
                "segments": [{"text": "words", "start": 0.0, "end": duration}],
                "presenter": "fullscreen",
                "overlay": None,
                "transition": {"type": "cut", "dur": 0.0},
            }
            for index, duration in enumerate(measured)
        ],
    }


def _write_take(path: Path, seconds: float, fps: int = 30) -> Path:
    """Render a real CFR test clip of an exact length."""
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [FFMPEG, "-v", "error", "-y", "-f", "lavfi",
         "-i", f"testsrc2=size=320x180:rate={fps}:duration={seconds}",
         "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
         "-c:v", "libopenh264", "-b:v", "1M", "-c:a", "aac",
         "-fps_mode", "cfr", "-r", str(fps), "-ar", "48000",
         str(path)],
        check=True, capture_output=True)
    return path


# ── probing ───────────────────────────────────────────────────────────────────

@needs_ffmpeg
def test_presenter_frames_counts_the_real_stream(tmp_path):
    take = _write_take(tmp_path / "takes" / "take.mp4", 2.0)
    # 2.0s at 30fps; encoders can be a frame out either way, so allow ±1.
    assert abs(presenter_frames(take) - 60) <= 1


def test_presenter_frames_reports_a_missing_take(tmp_path):
    with pytest.raises(OSError, match="presenter"):
        presenter_frames(tmp_path / "takes" / "absent.mp4")


# ── the guard ─────────────────────────────────────────────────────────────────

@needs_ffmpeg
def test_a_take_long_enough_for_its_timeline_passes(tmp_path):
    _write_take(tmp_path / "takes" / "take.mp4", 4.0)
    document = _document([1.5, 1.5])  # 3.0s of a 4.0s take
    assert validate_take_length(document, tmp_path) is True


@needs_ffmpeg
def test_a_short_take_is_rejected_naming_the_scene_and_shortfall(tmp_path):
    """The whole point: fail loudly instead of truncating in silence."""
    _write_take(tmp_path / "takes" / "take.mp4", 2.0)
    document = _document([1.5, 1.5])  # needs 3.0s, take is 2.0s

    with pytest.raises(TakeTooShortError) as raised:
        validate_take_length(document, tmp_path)

    message = str(raised.value)
    assert "scene-1" in message, "the failing scene must be named"
    assert "1.0" in message, "the shortfall in seconds must be stated"
    assert "reconcile" in message, "the message must point at the fix"


@needs_ffmpeg
def test_the_guard_tolerates_a_sub_frame_rounding_difference(tmp_path):
    """A take one frame short of an exact fit must not fail the build.

    Encoders routinely land a frame either side of the requested duration, so a
    zero-tolerance check would reject correct documents. The tolerance is one
    frame -- the same tolerance the board duration guard uses.
    """
    _write_take(tmp_path / "takes" / "take.mp4", 2.0)
    document = _document([2.0])  # exactly the take length
    assert validate_take_length(document, tmp_path) is True


@needs_ffmpeg
def test_transition_overlap_does_not_count_against_the_take(tmp_path):
    """Overlaps shorten the programme but NOT the take time consumed.

    Scenes are cut from a continuous recording, so a dissolve overlaps their
    *output* positions while each scene still consumes its own take footage.
    The guard must measure take time, not programme time, or it would wrongly
    pass a short take whenever transitions were used.
    """
    _write_take(tmp_path / "takes" / "take.mp4", 2.5)
    document = _document([1.5, 1.5])
    document["scenes"][1]["transition"] = {"type": "dissolve", "dur": 0.5}
    # Programme is 2.5s after the overlap, but the take must still supply 3.0s.
    with pytest.raises(TakeTooShortError):
        validate_take_length(document, tmp_path)


# ── wired into the render ─────────────────────────────────────────────────────

@needs_ffmpeg
def test_render_refuses_a_document_its_take_cannot_satisfy(tmp_path):
    """`impromptu render` must fail before mlt-melt, not truncate."""
    production = tmp_path / "chapter-1"
    _write_take(production / "takes" / "take.mp4", 2.0)
    (production / "out").mkdir(parents=True, exist_ok=True)
    import yaml
    (production / "production.yaml").write_text(yaml.safe_dump(_document([1.5, 1.5])))

    def runner(*args, **kwargs):  # must never be reached
        raise AssertionError("mlt-melt ran despite an impossible timeline")

    with pytest.raises(TakeTooShortError):
        render_production(production, runner=runner)


@needs_ffmpeg
def test_the_render_guard_error_is_reported_by_the_cli(tmp_path, monkeypatch, capsys):
    """A DocumentError subclass, so the existing CLI handler already prints it."""
    import impromptu

    production = tmp_path / "chapter-1"
    _write_take(production / "takes" / "take.mp4", 2.0)
    (production / "out").mkdir(parents=True, exist_ok=True)
    import yaml
    (production / "production.yaml").write_text(yaml.safe_dump(_document([1.5, 1.5])))

    monkeypatch.setattr(
        impromptu.sys, "argv", ["impromptu", "render", str(production)])
    with pytest.raises(SystemExit) as raised:
        impromptu.main()

    assert raised.value.code == 1
    output = capsys.readouterr().out
    assert "render failed" in output
    assert "scene-1" in output


def test_take_too_short_is_a_document_error():
    """So every existing `except DocumentError` path reports it without change."""
    assert issubclass(TakeTooShortError, DocumentError)
