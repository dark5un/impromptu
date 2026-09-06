import sys
import xml.etree.ElementTree as ET
from pathlib import Path

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
    assert root.find("tractor/track[@producer='presenter-track']") is not None
    assert root.find("tractor/track[@producer='overlay-track']") is not None
    assert root.find("tractor/transition[@id='audio-mix']") is not None
    assert "real_time" not in ET.tostring(root, encoding="unicode")


def test_melt_command_is_deterministic():
    command = melt_command("project.mlt", "out.mp4", threads=2)
    assert command[:3] == ["mlt-melt", "project.mlt", "real_time=-1"]
    assert "threads=2" in command


def test_parse_melt_progress():
    assert parse_progress("position=42") == 42.0
    assert parse_progress("nothing") is None
