"""Task 6 (RED): validate_plan() fails fast with line numbers."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from impromptu import validate_plan

BASE = {"fps": 30, "width": 1280, "height": 720}


def plan_with(scenes):
    return dict(BASE, scenes=scenes)


def test_valid_plan_passes():
    p = plan_with([
        {"mode": "fullscreen", "graphic": None, "start_sec": 0.0, "end_sec": 5.0,
         "transition": "fade", "transition_duration": 0.5},
        {"mode": "corner", "graphic": 0, "start_sec": 5.0, "end_sec": 10.0,
         "transition": "slideleft", "transition_duration": 0.5,
         "pip_position": "bottom-right"},
    ])
    assert validate_plan(p, num_graphics=1) == []


def test_non_contiguous_scenes_fail():
    p = plan_with([
        {"mode": "fullscreen", "graphic": None, "start_sec": 0.0, "end_sec": 5.0},
        {"mode": "fullscreen", "graphic": None, "start_sec": 6.0, "end_sec": 10.0},
    ])
    errs = validate_plan(p, num_graphics=0)
    assert any("contiguous" in e for e in errs), errs


def test_graphic_index_out_of_bounds_fails():
    p = plan_with([
        {"mode": "corner", "graphic": 3, "start_sec": 0.0, "end_sec": 5.0},
    ])
    errs = validate_plan(p, num_graphics=2)
    assert any("graphic" in e for e in errs), errs


def test_bad_mode_fails():
    p = plan_with([
        {"mode": "explode", "graphic": None, "start_sec": 0.0, "end_sec": 5.0},
    ])
    errs = validate_plan(p, num_graphics=0)
    assert any("mode" in e for e in errs), errs


def test_bad_transition_fails():
    p = plan_with([
        {"mode": "fullscreen", "graphic": None, "start_sec": 0.0, "end_sec": 5.0,
         "transition": "warpdrive"},
    ])
    errs = validate_plan(p, num_graphics=0)
    assert any("transition" in e for e in errs), errs


def test_bad_pip_position_fails():
    p = plan_with([
        {"mode": "corner", "graphic": 0, "start_sec": 0.0, "end_sec": 5.0,
         "pip_position": "middle-earth"},
    ])
    errs = validate_plan(p, num_graphics=1)
    assert any("pip_position" in e for e in errs), errs


def test_negative_timing_fails():
    p = plan_with([
        {"mode": "fullscreen", "graphic": None, "start_sec": 5.0, "end_sec": 5.0},
    ])
    errs = validate_plan(p, num_graphics=0)
    assert errs, "zero-length scene must fail"
