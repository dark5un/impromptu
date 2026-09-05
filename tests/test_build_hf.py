"""Task 11 (RED): build-hf generates a valid HyperFrames project (golden file)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from impromptu import build_hf_project, validate_plan

PLAN = {
    "fps": 30, "width": 1920, "height": 1080,
    "scenes": [
        {"mode": "fullscreen", "graphic": None, "title": "Hook",
         "start_sec": 0.0, "end_sec": 5.0,
         "transition": "fade", "transition_duration": 0.5},
        {"mode": "corner", "graphic": 0, "title": "Numbers",
         "start_sec": 5.0, "end_sec": 12.0,
         "transition": "fade", "transition_duration": 0.5,
         "pip_position": "bottom-right", "pip_scale": 0.25},
    ],
}


def test_plan_fixture_is_valid():
    assert validate_plan(PLAN, num_graphics=1) == []


def test_build_hf_emits_real_contract(tmp_path):
    out = tmp_path / "hf_project"
    index = build_hf_project(PLAN, presenter_src="presenter_raw.mp4",
                             presenter_duration=12.0, out_dir=out)
    html = Path(index).read_text()
    # root composition
    assert 'data-composition-id="main"' in html
    assert 'data-duration="12' in html
    assert 'data-width="1920"' in html and 'data-height="1080"' in html
    # a-roll presenter clip per blank template
    assert 'id="a-roll"' in html and 'class="clip"' in html
    assert 'data-track-index="0"' in html
    assert "presenter_raw.mp4" in html
    # graphic overlay clip on a higher track with timing
    assert 'data-start="5' in html and 'data-duration="7' in html
    assert 'data-track-index="1"' in html
    # ONE paused timeline registered — the renderer seeks this per frame
    assert "gsap.timeline({ paused: true })" in html
    assert 'window.__timelines["main"]' in html
    # NO trace of the fake __hf protocol
    assert "window.__hf" not in html
    # PiP corner scene positions the presenter absolutely
    assert "pip" in html.lower()


def test_build_hf_rejects_bad_plan(tmp_path):
    bad = dict(PLAN, scenes=[dict(PLAN["scenes"][0], mode="explode")])
    try:
        build_hf_project(bad, presenter_src="p.mp4", presenter_duration=5.0,
                         out_dir=tmp_path / "x")
    except ValueError as e:
        assert "scene[0]" in str(e)
    else:
        raise AssertionError("expected ValueError for bad mode")
