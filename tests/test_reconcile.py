import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.reconcile import reconcile_document


def document():
    return {
        "schema": 1, "title": "Demo",
        "target": {"orientation": "landscape", "resolution": [1920, 1080], "fps": 30},
        "media": {}, "presenter": {"source": "take.mp4"},
        "scenes": [
            {"id": "one", "say": "Hello world", "planned_sec": 2,
             "measured_sec": None, "segments": None, "presenter": "fullscreen",
             "overlay": None, "transition": {"type": "cut", "dur": 0}},
            {"id": "two", "say": "Goodbye now", "planned_sec": 3,
             "measured_sec": None, "segments": None, "presenter": "fullscreen",
             "overlay": None, "transition": {"type": "cut", "dur": 0}},
        ],
    }


def test_reconcile_fixture_writes_scene_relative_segments_and_drift(tmp_path):
    transcript = tmp_path / "transcript.json"
    transcript.write_text(json.dumps({"transcription": [
        {"timestamps": {"from": "00:00:00,000", "to": "00:00:01,200"}, "text": "Hello world"},
        {"timestamps": {"from": "00:00:01,200", "to": "00:00:03,800"}, "text": "Goodbye now"},
    ]}))
    output = tmp_path / "production.yaml"
    import yaml
    output.write_text(yaml.safe_dump(document(), sort_keys=False))

    result = reconcile_document(output, transcript_json=transcript)

    assert result["scenes"][0]["measured_sec"] == 1.2
    assert result["scenes"][0]["segments"] == [{"text": "Hello world", "start": 0.0, "end": 1.2}]
    assert result["scenes"][1]["measured_sec"] == 2.6
    assert result["scenes"][1]["segments"][0]["start"] == 0.0
    assert result["drift"][1]["planned_sec"] == 3.0
    assert yaml.safe_load(output.read_text())["scenes"][1]["measured_sec"] == 2.6


def test_reconcile_accepts_simple_whisper_segments(tmp_path):
    import yaml
    output = tmp_path / "production.yaml"
    output.write_text(yaml.safe_dump(document(), sort_keys=False))
    transcript = tmp_path / "segments.json"
    transcript.write_text(json.dumps({"segments": [
        {"start": 0, "end": 1, "text": "Hello world"},
        {"start": 1, "end": 2, "text": "Goodbye now"},
    ]}))

    result = reconcile_document(output, transcript_json=transcript)
    assert result["scenes"][0]["segments"][0]["text"] == "Hello world"


def test_reconcile_runs_whisper_json_subprocess(tmp_path):
    import yaml
    output = tmp_path / "production.yaml"
    output.write_text(yaml.safe_dump(document(), sort_keys=False))
    script = tmp_path / "whisper";
    script.write_text("#!/bin/sh\nprintf '%s' '{\"segments\":[{\"start\":0,\"end\":1,\"text\":\"Hello world\"},{\"start\":1,\"end\":2,\"text\":\"Goodbye now\"}]}'\n")
    script.chmod(0o755)

    result = reconcile_document(output, take=tmp_path / "take.mp4", whisper_command=[str(script)])
    assert result["scenes"][0]["measured_sec"] == 1.0
