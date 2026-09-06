import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.document import validate_document
from render.melt import melt_command, parse_progress
from render.mlt_xml import document_to_xml


def document():
    return {
        "schema": 1, "title": "Demo",
        "target": {"orientation": "landscape", "resolution": [1920, 1080], "fps": 30},
        "media": {"chart": {"type": "board", "src": "boards/chart.mov"}},
        "presenter": {"source": "takes/take.mp4"},
        "scenes": [
            {"id": "one", "say": "One", "planned_sec": 2, "measured_sec": 2,
             "segments": None, "presenter": "fullscreen", "overlay": None,
             "transition": {"type": "cut", "dur": 0}},
            {"id": "two", "say": "Two", "planned_sec": 3, "measured_sec": 3,
             "segments": None, "presenter": "corner", "overlay": "chart",
             "transition": {"type": "dissolve", "dur": 0.4}},
        ],
    }


def test_document_fixture_is_valid():
    assert validate_document(document()) == []


def test_mlt_xml_has_named_tracks_and_audio_mix():
    tree = document_to_xml(document(), "/project")
    root = tree.getroot()
    # Scenes alternate across two presenter playlists so neighbours can overlap
    # for a transition; the programme tractor is then composited with overlays.
    assert root.find("playlist[@id='presenter-a']") is not None
    assert root.find("playlist[@id='presenter-b']") is not None
    assert root.find("playlist[@id='overlay-bed']") is not None
    program = root.find("tractor[@id='presenter-program']")
    assert program is not None
    assert program.find("transition[@id='presenter-audio']") is not None
    assert "real_time" not in ET.tostring(root, encoding="unicode")


def test_melt_command_is_deterministic():
    command = melt_command("project.mlt", "out.mp4", threads=2)
    assert command[:3] == ["mlt-melt", "project.mlt", "real_time=-1"]
    assert "threads=2" in command


def test_parse_melt_progress():
    assert parse_progress("position=42") == 42.0
    assert parse_progress("nothing") is None


# ── encoder selection ────────────────────────────────────────────────────────

def test_melt_command_pins_an_h264_encoder_and_quality():
    """Regression: MLT's avformat default is mpeg4 Simple Profile.

    Left unspecified it produced visibly blocky 1080p at ~1.5 Mbps. The
    deliverable is H.264, so the codec and a quality target must be explicit.
    """
    from render.melt import melt_command

    command = melt_command("project.mlt", "out.mp4", threads=2)
    joined = " ".join(command)
    assert "vcodec=" in joined, "encoder must be explicit, not MLT's mpeg4 default"
    assert "mpeg4" not in joined
    # a quality target: CRF for x264, bitrate for the CRF-less libopenh264
    assert "crf=" in joined or "vb=" in joined
    assert "acodec=aac" in joined
    assert "movflags=+faststart" in joined


def test_h264_encoder_prefers_x264_then_falls_back(monkeypatch):
    """libopenh264 is the fallback where libx264 is absent.

    The container installs RPM Fusion's full ffmpeg so libx264 is present, but
    a bare Fedora host with ffmpeg-free has only libopenh264.
    """
    from render import melt

    monkeypatch.setattr(melt, "_encoder_available", lambda name: name == "libx264")
    assert melt.h264_encoder() == "libx264"

    monkeypatch.setattr(melt, "_encoder_available", lambda name: name == "libopenh264")
    assert melt.h264_encoder() == "libopenh264"


def test_x264_uses_crf_and_openh264_uses_bitrate(monkeypatch):
    """libopenh264 has no CRF support, so quality must be expressed as bitrate."""
    from render import melt

    monkeypatch.setattr(melt, "h264_encoder", lambda: "libx264")
    assert any(part.startswith("crf=") for part in melt.melt_command("p.mlt", "o.mp4"))

    monkeypatch.setattr(melt, "h264_encoder", lambda: "libopenh264")
    command = melt.melt_command("p.mlt", "o.mp4")
    assert any(part.startswith("vb=") for part in command)
    assert not any(part.startswith("crf=") for part in command)


def test_missing_h264_encoder_is_an_explicit_error(monkeypatch):
    from render import melt

    monkeypatch.setattr(melt, "_encoder_available", lambda name: False)
    with pytest.raises(melt.MeltError, match="H.264"):
        melt.h264_encoder()
