"""Task 13 (RED): composite --graphics-track uses one full-length graphic input."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from impromptu import build_filtergraph, validate_plan

PLAN = {
    "fps": 30, "width": 320, "height": 180,
    "scenes": [
        {"mode": "fullscreen", "graphic": None,
         "start_sec": 0.0, "end_sec": 3.0,
         "transition": "fade", "transition_duration": 0.5},
        {"mode": "bg_only", "graphic": 0,
         "start_sec": 3.0, "end_sec": 6.0,
         "transition": "fade", "transition_duration": 0.5},
    ],
}


def test_graphics_track_single_input():
    # one full-length input; scene references time ranges, not file indices
    fg, _, _ = build_filtergraph(PLAN, num_graphics=1, graphics_track=True)
    assert "[1:v]trim=start=3.0:end=6.0" in fg
    # no per-file [g_idx+1] indexing beyond input 1
    assert "[2:v]" not in fg


def test_graphics_track_still_validates():
    assert validate_plan(PLAN, num_graphics=1) == []
