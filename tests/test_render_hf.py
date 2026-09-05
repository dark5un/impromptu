"""Task 12/14 (RED): render_hf_cmd builds the correct one-shot podman command."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from impromptu import render_hf_cmd, RENDER_IMAGE


def test_render_cmd_mounts_and_flags(tmp_path):
    proj = tmp_path / "hf_project"
    proj.mkdir()
    out = tmp_path / "out" / "gfx.mp4"
    cmd = render_hf_cmd(str(proj), str(out), fps="30", quality="draft")
    assert cmd[:3] == ["podman", "run", "--rm"]
    assert f"{proj.resolve()}:/project:ro,Z" in cmd
    assert f"{(tmp_path / 'out').resolve()}:/output:Z" in cmd
    assert RENDER_IMAGE in cmd
    assert "/project" in cmd
    assert cmd[cmd.index("--output") + 1] == "/output/gfx.mp4"
    assert cmd[cmd.index("--fps") + 1] == "30"
    assert cmd[cmd.index("--quality") + 1] == "draft"
    assert cmd[cmd.index("--format") + 1] == "mp4"
