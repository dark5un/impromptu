import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.migrate import migrate_v1


def test_migrate_v1_fixture_resolves_graphic_indices(tmp_path):
    source = tmp_path / "v1"
    source.mkdir()
    (source / "script.md").write_text(
        "# Demo\n\n## Hook\nHello there.\n\n## Numbers\nHere are the numbers.\n"
    )
    (source / "scene-plan.json").write_text(json.dumps({
        "fps": 30, "width": 1920, "height": 1080,
        "graphics": ["graphics/chart.mp4"],
        "scenes": [
            {"mode": "fullscreen", "graphic": None, "title": "Hook",
             "start_sec": 0, "end_sec": 2},
            {"mode": "corner", "graphic": 0, "title": "Numbers",
             "start_sec": 2, "end_sec": 5},
        ],
    }))
    output = tmp_path / "production.yaml"

    document = migrate_v1(source / "script.md", source / "scene-plan.json", output)

    assert document["media"]["graphic-1"] == {"type": "video", "src": "graphics/chart.mp4"}
    assert document["scenes"][1]["overlay"] == "graphic-1"
    assert document["scenes"][0]["say"] == "Hello there."
    assert yaml.safe_load(output.read_text()) == document


def test_migrate_v1_uses_graphics_mapping_and_preserves_scene_defaults(tmp_path):
    script = tmp_path / "script.md"
    plan = tmp_path / "scene-plan.json"
    script.write_text("# Title\n\n## First\nSay this.\n")
    plan.write_text(json.dumps({"scenes": [{"mode": "fullscreen", "graphic": None,
                                             "start_sec": 0, "end_sec": 1}]}))

    document = migrate_v1(script, plan, tmp_path / "production.yaml")

    assert document["title"] == "Title"
    scene = document["scenes"][0]
    assert scene["presenter"] == "fullscreen"
    assert scene["overlay"] is None
    assert scene["transition"] == {"type": "cut", "dur": 0.0}


def test_migrate_v1_rejects_unknown_graphic_index(tmp_path):
    script = tmp_path / "script.md"
    plan = tmp_path / "scene-plan.json"
    script.write_text("# Title\n\n## First\nSay this.\n")
    plan.write_text(json.dumps({"scenes": [{"graphic": 2, "start_sec": 0, "end_sec": 1}]}))

    import pytest
    with pytest.raises(ValueError, match="graphic index"):
        migrate_v1(script, plan, tmp_path / "production.yaml")


def test_validate_cli_is_available(tmp_path):
    path = tmp_path / "production.yaml"
    path.write_text("schema: 1\n")
    result = __import__("subprocess").run(
        [sys.executable, "impromptu.py", "validate", str(tmp_path)],
        capture_output=True, text=True,
        cwd=Path(__file__).resolve().parent.parent,
    )
    assert result.returncode != 0
    assert "invalid" in (result.stdout + result.stderr).lower()
