"""Task 2 (RED): chained-xfade offsets must be cumulative for 3+ scenes.

Bug: offset was computed as prev_scene_dur - td, but after the first xfade
the running stream's duration is sum(durations) - sum(tds). Correct:
track running_dur; each step offset = running_dur - td, then
running_dur = running_dur + scene_dur - td.

Fixture: 3 scenes of 10s each, transition_duration 0.5, transition fade.
Expected: offsets [9.5, 19.0].
Buggy code produces: [9.5, 9.5].
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from impromptu import build_filtergraph


def make_plan():
    return {
        "fps": 30, "width": 1280, "height": 720,
        "scenes": [
            {"mode": "fullscreen", "graphic": None,
             "start_sec": 0.0, "end_sec": 10.0,
             "transition": "fade", "transition_duration": 0.5},
            {"mode": "fullscreen", "graphic": None,
             "start_sec": 10.0, "end_sec": 20.0,
             "transition": "fade", "transition_duration": 0.5},
            {"mode": "fullscreen", "graphic": None,
             "start_sec": 20.0, "end_sec": 30.0,
             "transition": "fade", "transition_duration": 0.5},
        ],
    }


def test_chained_xfade_offsets_are_cumulative():
    fg, _, _ = build_filtergraph(make_plan(), num_graphics=0)
    offsets = [float(m) for m in re.findall(r"xfade=transition=\w+:d=[\d.]+:offset=([\d.]+)", fg)]
    assert offsets == [9.5, 19.0], f"offsets not cumulative: {offsets}"
