"""Strict v2 direct/render/package contracts."""
from pathlib import Path

import pytest

from core.direct import direct_document
from render.pipeline import package_production, render_production


@pytest.fixture
def production():
    return {
        "schema": 1,
        "title": "Demo",
        "target": {"orientation": "landscape", "resolution": [1920, 1080], "fps": 30},
        "media": {
            "chart": {"type": "board", "src": "boards/chart.html"},
            "racks": {"type": "video", "src": "media/racks.mp4"},
        },
        "presenter": {"source": "takes/take.mp4"},
        "scenes": [
            {"id": "hook", "say": "Start", "planned_sec": 2.0, "measured_sec": 2.0,
             "segments": None, "presenter": "fullscreen", "overlay": None, "transition": {"type": "cut", "dur": 0.0}},
            {"id": "numbers", "say": "Numbers", "planned_sec": 3.0, "measured_sec": 3.0,
             "segments": None, "presenter": "corner", "overlay": "chart", "transition": {"type": "dissolve", "dur": 0.4}},
            {"id": "b-roll", "say": "Watch", "planned_sec": 4.0, "measured_sec": 4.0,
             "segments": None, "presenter": "hidden", "overlay": "racks", "transition": {"type": "dissolve", "dur": 0.4}},
        ],
    }


def test_direct_assigns_treatment_and_transition_from_media(production):
    result = direct_document(production)
    assert [scene["presenter"] for scene in result["scenes"]] == ["fullscreen", "corner", "hidden"]
    assert result["scenes"][0]["transition"] == {"type": "cut", "dur": 0.0}
    assert result["scenes"][1]["transition"] == {"type": "dissolve", "dur": 0.4}
    assert result["scenes"][2]["transition"] == {"type": "dissolve", "dur": 0.4}


def test_render_production_writes_document_mlt_and_runs_renderer(tmp_path, production):
    import yaml

    (tmp_path / "production.yaml").write_text(yaml.safe_dump(production, sort_keys=False))
    calls = []

    def runner(project, output, threads=1):
        calls.append((project, output, threads))
        Path(output).write_bytes(b"master")

    result = render_production(tmp_path, runner=runner)
    assert result == tmp_path / "out" / "master.mp4"
    assert (tmp_path / "out" / "production.mlt").exists()
    assert calls == [(tmp_path / "out" / "production.mlt", result, 1)]


def test_package_production_orchestrates_master_and_metadata(tmp_path, production):
    import yaml

    (tmp_path / "production.yaml").write_text(yaml.safe_dump(production, sort_keys=False))
    master = tmp_path / "out" / "master.mp4"
    master.parent.mkdir()
    master.write_bytes(b"master")
    calls = []

    def command_runner(command, check=True):
        calls.append(command)
        if "loudnorm" in " ".join(command):
            (tmp_path / "out" / "master-loudnorm.mp4").write_bytes(b"loud")
        elif "thumbnail" in command:
            (tmp_path / "out" / "thumbnail.png").write_bytes(b"png")

    result = package_production(tmp_path, runner=command_runner)
    assert result["master"] == tmp_path / "out" / "master-loudnorm.mp4"
    assert (tmp_path / "out" / "chapters.txt").read_text().startswith("00:00 hook")
    assert (tmp_path / "out" / "description.md").exists()
    assert (tmp_path / "out" / "upload-checklist.md").exists()
    assert len(calls) == 2
    assert any("loudnorm" in " ".join(command) for command in calls)


def test_render_and_package_require_production_yaml(tmp_path):
    with pytest.raises(FileNotFoundError):
        render_production(tmp_path)
    with pytest.raises(FileNotFoundError):
        package_production(tmp_path)
