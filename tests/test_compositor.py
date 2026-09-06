"""Compositor contracts: transitions, PiP treatment, and overlay placement.

These cover the five defects found by auditing the v2 plan against the code:
generated XML dropped `transition` and `presenter` entirely, overlay blanks were
measured from zero instead of from the previous entry, boards reached MLT as
HTML, and `direct` overwrote human decisions.

Service choice is empirical, not from the plan's prose: `affine` composites
ProRes 4444 alpha correctly on MLT 7.36.1 while `qtblend` discards either the
board or the presenter.  See docs/decisions.md.
"""
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.direct import direct_document
from core.document import validate_document
from render.mlt_xml import document_to_xml, scene_layout


def document(**overrides):
    doc = {
        "schema": 1,
        "title": "Demo",
        "target": {"orientation": "landscape", "resolution": [1920, 1080], "fps": 30},
        "media": {
            "chart": {"type": "board", "src": "boards/chart.html"},
            "racks": {"type": "video", "src": "media/racks.mp4"},
        },
        "presenter": {"source": "takes/take.mp4"},
        "scenes": [
            {"id": "hook", "say": "Start", "planned_sec": 10.0, "measured_sec": 10.0,
             "segments": None, "presenter": "fullscreen", "overlay": None,
             "transition": {"type": "cut", "dur": 0.0}},
            {"id": "numbers", "say": "Numbers", "planned_sec": 10.0, "measured_sec": 10.0,
             "segments": None, "presenter": "corner", "overlay": "chart",
             "transition": {"type": "dissolve", "dur": 0.5}},
            {"id": "gap", "say": "Gap", "planned_sec": 10.0, "measured_sec": 10.0,
             "segments": None, "presenter": "fullscreen", "overlay": None,
             "transition": {"type": "cut", "dur": 0.0}},
            {"id": "broll", "say": "Watch", "planned_sec": 10.0, "measured_sec": 10.0,
             "segments": None, "presenter": "hidden", "overlay": "racks",
             "transition": {"type": "wipeleft", "dur": 0.4}},
        ],
    }
    doc.update(overrides)
    return doc


def test_fixture_is_a_valid_document():
    assert validate_document(document()) == []


# ── scene layout: transitions shorten the programme by their overlap ──────────

def test_layout_overlaps_scenes_by_transition_duration():
    layout = scene_layout(document())
    # cut = no overlap, so scene 1 starts where scene 0 ends
    assert layout[0]["program_start"] == pytest.approx(0.0)
    # dissolve 0.5s pulls scene 1 back into scene 0 by 0.5s
    assert layout[1]["program_start"] == pytest.approx(9.5)
    # cut after a dissolve: 9.5 + 10 = 19.5
    assert layout[2]["program_start"] == pytest.approx(19.5)
    # wipeleft 0.4s
    assert layout[3]["program_start"] == pytest.approx(29.1)


def test_layout_take_offsets_are_consecutive_in_the_source_take():
    """The presenter take is one continuous recording, so in-points accumulate."""
    layout = scene_layout(document())
    assert [item["take_start"] for item in layout] == pytest.approx([0.0, 10.0, 20.0, 30.0])


def test_layout_clamps_a_transition_longer_than_its_scenes():
    doc = document()
    doc["scenes"][1]["transition"] = {"type": "dissolve", "dur": 99.0}
    layout = scene_layout(doc)
    # cannot overlap more than the shorter neighbouring scene
    assert layout[1]["program_start"] >= 0.0
    assert layout[1]["transition_frames"] <= 10.0 * 30


def test_first_scene_never_carries_a_transition():
    doc = document()
    doc["scenes"][0]["transition"] = {"type": "dissolve", "dur": 2.0}
    layout = scene_layout(doc)
    assert layout[0]["program_start"] == pytest.approx(0.0)
    assert layout[0]["transition_frames"] == 0


# ── transitions must reach the XML ───────────────────────────────────────────

def test_dissolve_emits_a_luma_transition_over_the_overlap():
    root = document_to_xml(document(), "/p").getroot()
    lumas = [t for t in root.findall("tractor/transition")
             if t.findtext("property[@name='mlt_service']") == "luma"]
    assert lumas, "dissolve/wipe scenes must emit luma transitions"
    # 0.5s dissolve at 30fps = 15 frames, placed at the overlap
    spans = {(t.get("in"), t.get("out")) for t in lumas}
    assert ("285", "299") in spans


def test_cut_emits_no_transition_for_that_boundary():
    doc = document()
    for scene in doc["scenes"][1:]:
        scene["transition"] = {"type": "cut", "dur": 0.0}
    root = document_to_xml(doc, "/p").getroot()
    lumas = [t for t in root.findall("tractor/transition")
             if t.findtext("property[@name='mlt_service']") == "luma"]
    assert lumas == []


def test_wipe_uses_a_luma_resource_and_dissolve_does_not():
    """A wipe needs a luma map; a plain dissolve must not reference one."""
    doc = document()
    doc["scenes"][1]["transition"] = {"type": "dissolve", "dur": 0.5}
    doc["scenes"][3]["transition"] = {"type": "wipeleft", "dur": 0.4}
    root = document_to_xml(doc, "/p").getroot()
    by_span = {}
    for t in root.findall("tractor/transition"):
        if t.findtext("property[@name='mlt_service']") == "luma":
            by_span[t.get("in")] = t.findtext("property[@name='resource']")
    resources = list(by_span.values())
    assert any(r is None for r in resources), "dissolve must have no luma map"
    assert any(r and r.endswith(".pgm") for r in resources), "wipe needs a luma map"


def test_audio_is_mixed_across_the_transition_overlap():
    root = document_to_xml(document(), "/p").getroot()
    mixes = [t for t in root.findall("tractor/transition")
             if t.findtext("property[@name='mlt_service']") == "mix"]
    assert mixes, "overlapping presenter tracks must mix audio, not silence one"
    assert all(t.findtext("property[@name='sum']") == "1" for t in mixes)


# ── presenter treatment must reach the XML ───────────────────────────────────

def test_corner_presenter_emits_a_pip_rect():
    root = document_to_xml(document(), "/p").getroot()
    xml = document_to_xml(document(), "/p")
    affines = [t for t in root.findall("tractor/transition")
               if t.findtext("property[@name='mlt_service']") == "affine"]
    assert affines, "compositing must use affine (qtblend drops ProRes alpha)"
    rects = [t.findtext("property[@name='rect']") for t in affines]
    assert any(r and "25%x25%" in r for r in rects), f"no PiP rect found in {rects}"
    del xml


def test_hidden_presenter_is_not_composited_over_the_overlay():
    """A pure b-roll scene shows the media fullscreen with no presenter inset."""
    doc = document()
    layout = scene_layout(doc)
    broll = layout[3]
    assert broll["presenter"] == "hidden"
    assert broll["pip_rect"] is None


def test_overlay_z_order_depends_on_presenter_treatment():
    """A lower third sits OVER the presenter; a chart the presenter insets INTO.

    Regression: one overlay track meant a fullscreen presenter covered its own
    board, so `fullscreen` + board rendered with the board invisible.
    """
    doc = document()
    doc["scenes"][1]["presenter"] = "fullscreen"   # board over presenter
    doc["scenes"][3]["presenter"] = "hidden"       # b-roll replaces presenter
    root = document_to_xml(doc, "/p").getroot()
    top = root.find("playlist[@id='overlay-top']")
    bed = root.find("playlist[@id='overlay-bed']")
    assert top is not None and bed is not None
    top_media = [e.get("producer") for e in top if e.tag == "entry"]
    bed_media = [e.get("producer") for e in bed if e.tag == "entry"]
    assert top_media == ["media-chart"], top_media
    assert bed_media == ["media-racks"], bed_media


def test_corner_presenter_puts_its_board_on_the_bed_track():
    doc = document()
    root = document_to_xml(doc, "/p").getroot()
    bed = root.find("playlist[@id='overlay-bed']")
    assert [e.get("producer") for e in bed if e.tag == "entry"] == [
        "media-chart", "media-racks"]


def test_track_order_places_bed_below_presenter_and_top_above():
    doc = document()
    doc["scenes"][1]["presenter"] = "fullscreen"
    root = document_to_xml(doc, "/p").getroot()
    tracks = [t.get("producer") for t in root.findall("tractor[@id='main']/track")]
    assert tracks.index("overlay-bed") < tracks.index("presenter-program")
    assert tracks.index("presenter-program") < tracks.index("overlay-top")


def test_fullscreen_presenter_has_no_pip_rect():
    layout = scene_layout(document())
    assert layout[0]["pip_rect"] is None
    assert layout[1]["pip_rect"] is not None


def test_pip_opacity_is_percent_not_unit_scale():
    """affine's rect opacity field is a percentage; ':1' would be near-invisible."""
    layout = scene_layout(document())
    rect = layout[1]["pip_rect"]
    assert rect.endswith(":100%"), f"expected percent opacity, got {rect!r}"


# ── overlay placement ────────────────────────────────────────────────────────

def test_overlay_blank_is_measured_from_the_previous_entry_end():
    """Regression: blanks were computed from zero, shifting every later board."""
    root = document_to_xml(document(), "/p").getroot()
    # chart (corner) and racks (hidden) both sit on the bed track
    track = root.find("playlist[@id='overlay-bed']")
    assert track is not None
    kinds = [(child.tag, child.get("length") or child.get("producer")) for child in track]
    assert kinds[0][0] == "blank"
    producers = [value for tag, value in kinds if tag == "entry"]
    assert producers == ["media-chart", "media-racks"]
    blanks = [int(value) for tag, value in kinds if tag == "blank"]
    entries = [child for child in track if child.tag == "entry"]
    total = sum(blanks) + sum(int(e.get("out")) - int(e.get("in")) + 1 for e in entries)
    layout = scene_layout(document())
    program_frames = round((layout[-1]["program_start"] + layout[-1]["duration"]) * 30)
    assert total <= program_frames
    # scene 1 starts at 9.5s -> frame 285, so the leading blank is exactly that
    assert blanks[0] == 285


def test_boards_resolve_to_the_rendered_mov_not_the_source_html():
    """Regression: MLT was handed boards/chart.html, which it cannot decode."""
    doc = document()
    resolved = {"chart": Path("/p/.cache/boards/chart-abc123.mov")}
    root = document_to_xml(doc, "/p", boards=resolved).getroot()
    resources = [p.text for p in root.findall("producer/property[@name='resource']")]
    assert not any(r.endswith(".html") for r in resources), resources
    assert "/p/.cache/boards/chart-abc123.mov" in resources


def test_unrendered_board_is_a_build_error_not_a_broken_render():
    doc = document()
    with pytest.raises(ValueError, match="chart"):
        document_to_xml(doc, "/p", boards={}, require_boards=True)


# ── direct must not clobber human decisions ──────────────────────────────────

def test_direct_fills_only_null_fields():
    doc = document()
    doc["scenes"][3]["presenter"] = "hidden"
    doc["scenes"][3]["transition"] = {"type": "wipeleft", "dur": 0.8}
    result = direct_document(doc)
    assert result["scenes"][3]["presenter"] == "hidden"
    assert result["scenes"][3]["transition"] == {"type": "wipeleft", "dur": 0.8}


def test_direct_decides_null_fields():
    doc = document()
    doc["scenes"][1]["presenter"] = None
    doc["scenes"][1]["transition"] = None
    result = direct_document(doc)
    assert result["scenes"][1]["presenter"] == "corner"
    assert result["scenes"][1]["transition"]["type"] == "dissolve"


def test_direct_force_redecides_everything():
    doc = document()
    doc["scenes"][3]["presenter"] = "fullscreen"
    result = direct_document(doc, force=True)
    # racks is video b-roll, so the decision is 'hidden'
    assert result["scenes"][3]["presenter"] == "hidden"


def test_directed_document_round_trips_through_the_validator(tmp_path):
    directed = direct_document(document())
    assert validate_document(directed) == []
    path = tmp_path / "production.yaml"
    path.write_text(yaml.safe_dump(directed, sort_keys=False))
    assert validate_document(yaml.safe_load(path.read_text())) == []
