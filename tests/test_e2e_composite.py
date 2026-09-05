"""Task 14 (e2e): color-bar presenter + graphics -> final MP4 via real ffmpeg.

Small fixtures (320x180, mpeg4) so this runs in seconds. Asserts
duration/resolution/CFR via ffprobe.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from impromptu import probe_video

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")

PLAN = {
    "fps": 30, "width": 320, "height": 180,
    "scenes": [
        {"mode": "fullscreen", "graphic": None, "title": "Hook",
         "start_sec": 0.0, "end_sec": 4.5,
         "transition": "fade", "transition_duration": 0.5},
        {"mode": "bg_only", "graphic": 0, "title": "Numbers",
         "start_sec": 4.5, "end_sec": 9.0,
         "transition": "fade", "transition_duration": 0.5},
    ],
}


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-1500:]
    return r


def test_end_to_end_composite(tmp_path):
    run(["ffmpeg", "-y", "-v", "error",
         "-f", "lavfi", "-i", "color=c=red:s=320x180:r=30:d=4.5",
         "-f", "lavfi", "-i", "color=c=blue:s=320x180:r=30:d=4.5",
         "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo:d=9",
         "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[pv];[pv][2:a]concat=n=1:v=1:a=1[outv][outa]",
         "-map", "[outv]", "-map", "[outa]",
         "-c:v", "mpeg4", "-pix_fmt", "yuv420p", "-c:a", "aac",
         str(tmp_path / "presenter.mp4")])
    run(["ffmpeg", "-y", "-v", "error",
         "-f", "lavfi", "-i", "color=c=teal:s=320x180:r=30:d=9",
         "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo:d=9",
         "-c:v", "mpeg4", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
         str(tmp_path / "gfx.mp4")])
    (tmp_path / "plan.json").write_text(json.dumps(PLAN))
    import impromptu
    import argparse
    args = argparse.Namespace(
        scene_plan=str(tmp_path / "plan.json"),
        presenter=str(tmp_path / "presenter.mp4"),
        graphics=[str(tmp_path / "gfx.mp4")], graphics_track=None,
        output=str(tmp_path / "final.mp4"), normalize=False)
    impromptu.cmd_composite(args)
    info = probe_video(tmp_path / "final.mp4")
    assert info is not None
    assert info["width"] == 320 and info["height"] == 180
    # 9.0s of scenes minus one 0.5s transition overlap
    assert abs(info["duration"] - 8.5) < 0.3, info
    assert abs(info["fps"] - 30.0) < 0.5, info
