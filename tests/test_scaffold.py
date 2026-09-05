"""Task 10 (RED): scaffold creates the videos/<slug>/ layout with samples."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from impromptu import cmd_scaffold
import argparse


def run_scaffold(tmp_path):
    slug = tmp_path / "videos" / "demo"
    args = argparse.Namespace(path=str(slug))
    cmd_scaffold(args)
    return slug


def test_scaffold_creates_layout(tmp_path):
    slug = run_scaffold(tmp_path)
    assert (slug / "script.md").exists()
    assert (slug / "scene-plan.json").exists()
    assert (slug / "hf_project").is_dir()
    assert (slug / "graphics").is_dir()
    assert (slug / "out").is_dir()


def test_scaffold_scene_plan_is_valid(tmp_path):
    from impromptu import validate_plan
    slug = run_scaffold(tmp_path)
    plan = json.loads((slug / "scene-plan.json").read_text())
    assert validate_plan(plan, num_graphics=1) == []
    # timings must match the script.md scene annotations
    script = (slug / "script.md").read_text()
    for start, end in [(0, 12), (12, 35)]:
        assert f"({start}s-{end}s)" in script
