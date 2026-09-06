import json
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.document import validate_document
from core.reconcile import (
    ReconcileOverrunError,
    reconcile_data,
    reconcile_document,
    validate_measured_within_take,
)


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
    output.write_text(yaml.safe_dump(document(), sort_keys=False))

    result = reconcile_document(output, transcript_json=transcript)

    assert result["scenes"][0]["measured_sec"] == 1.2
    assert result["scenes"][0]["segments"] == [{"text": "Hello world", "start": 0.0, "end": 1.2}]
    assert result["scenes"][1]["measured_sec"] == 2.6
    assert result["scenes"][1]["segments"][0]["start"] == 0.0
    assert result["drift"][1]["planned_sec"] == 3.0
    assert yaml.safe_load(output.read_text())["scenes"][1]["measured_sec"] == 2.6


def test_reconcile_accepts_simple_whisper_segments(tmp_path):
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
    output = tmp_path / "production.yaml"
    output.write_text(yaml.safe_dump(document(), sort_keys=False))
    script = tmp_path / "whisper"
    script.write_text("#!/bin/sh\nprintf '%s' '{\"segments\":[{\"start\":0,\"end\":1,\"text\":\"Hello world\"},{\"start\":1,\"end\":2,\"text\":\"Goodbye now\"}]}'\n")
    script.chmod(0o755)

    result = reconcile_document(output, take=tmp_path / "take.mp4", whisper_command=[str(script)])
    assert result["scenes"][0]["measured_sec"] == 1.0


# ── leading silence and gaps ─────────────────────────────────────────────────

def test_leading_silence_anchors_the_scene_at_first_speech():
    """A take rarely starts on the first syllable; the gap is not scene time."""
    doc = document()
    out, drift = reconcile_data(doc, [
        {"text": "Hello world", "start": 1.5, "end": 4.0},
        {"text": "Goodbye now", "start": 4.0, "end": 6.0},
    ])
    assert out["scenes"][0]["segments"][0]["start"] == 0.0
    assert out["scenes"][0]["measured_sec"] == pytest.approx(2.5)
    assert validate_document(out) == []


def test_reconciled_document_always_passes_its_own_validator():
    """Regression: reconcile emitted documents its own loader then rejected."""
    doc = document()
    out, _ = reconcile_data(doc, [
        {"text": "Hello world", "start": 3.25, "end": 5.0},
        {"text": "Goodbye now", "start": 7.5, "end": 9.75},
    ])
    assert validate_document(out) == []


def test_mid_scene_pause_stays_contiguous_and_non_negative():
    doc = document()
    out, _ = reconcile_data(doc, [
        {"text": "Hello", "start": 0.5, "end": 1.0},
        {"text": "world", "start": 2.8, "end": 3.4},
        {"text": "Goodbye now", "start": 5.0, "end": 6.0},
    ])
    for scene in out["scenes"]:
        starts = [segment["start"] for segment in scene["segments"]]
        assert all(value >= 0.0 for value in starts)
        assert starts == sorted(starts)
        if scene["segments"]:
            assert scene["segments"][0]["start"] == 0.0
            assert scene["segments"][-1]["end"] == pytest.approx(scene["measured_sec"])
    assert validate_document(out) == []


def test_rerunning_reconcile_replaces_rather_than_accumulates(tmp_path):
    output = tmp_path / "production.yaml"
    output.write_text(yaml.safe_dump(document(), sort_keys=False))
    first = tmp_path / "a.json"
    first.write_text(json.dumps({"segments": [
        {"start": 0, "end": 1, "text": "Hello world"},
        {"start": 1, "end": 2, "text": "Goodbye now"},
    ]}))
    second = tmp_path / "b.json"
    second.write_text(json.dumps({"segments": [
        {"start": 0, "end": 4, "text": "Hello world"},
        {"start": 4, "end": 9, "text": "Goodbye now"},
    ]}))

    reconcile_document(output, transcript_json=first)
    result = reconcile_document(output, transcript_json=second)

    assert len(result["scenes"][0]["segments"]) == 1
    assert result["scenes"][0]["measured_sec"] == 4.0
    assert result["scenes"][1]["measured_sec"] == 5.0
    assert validate_document(yaml.safe_load(output.read_text())) == []


def test_scene_with_no_matched_speech_falls_back_to_planned():
    doc = document()
    out, drift = reconcile_data(doc, [{"text": "Hello world", "start": 0.0, "end": 1.0}])
    assert out["scenes"][1]["measured_sec"] == 3.0
    assert out["scenes"][1]["segments"] == []
    assert drift[1]["delta_sec"] == 0.0
    assert validate_document(out) == []


# ── overrun guard: durations written must fit the take ──────────────────────

def test_reconcile_refuses_durations_that_overrun_the_take():
    """The guard that halts the error at the point the values are written: the
    sum of measured_sec must not exceed the take they were measured from,
    mirroring render's take-length guard but one step earlier."""
    doc = document()
    out, _ = reconcile_data(doc, [
        {"text": "Hello world", "start": 0.0, "end": 1.0},
        {"text": "Goodbye now", "start": 1.0, "end": 6.0},
    ])
    # scenes measure 1.0 and 5.0 -> 6.0s total against a 5.5s take: overrun.
    with pytest.raises(ReconcileOverrunError, match="take.mp4"):
        # 5.5s * 30fps = 165 frames available, 180 frames required.
        validate_measured_within_take(out, take_frames=165, fps=30)


def test_reconcile_accepts_durations_that_fit_the_take():
    doc = document()
    out, _ = reconcile_data(doc, [
        {"text": "Hello world", "start": 0.0, "end": 1.0},
        {"text": "Goodbye now", "start": 1.0, "end": 5.0},
    ])
    validate_measured_within_take(out, take_frames=200, fps=30)  # 6.67s available


def test_reconcile_overrun_guard_reports_the_shortfall():
    doc = document()
    out, _ = reconcile_data(doc, [
        {"text": "Hello world", "start": 0.0, "end": 1.0},
        {"text": "Goodbye now", "start": 1.0, "end": 9.0},
    ])
    with pytest.raises(ReconcileOverrunError) as excinfo:
        validate_measured_within_take(out, take_frames=120, fps=30)  # 4.0s take
    assert "3.0fps" in str(excinfo.value) or "overrun" in str(excinfo.value)


def test_reconcile_overrun_guard_one_frame_tolerance():
    """An exact fit must not fail, matching render's one-frame tolerance."""
    doc = document()
    out, _ = reconcile_data(doc, [
        {"text": "Hello world", "start": 0.0, "end": 1.0},
        {"text": "Goodbye now", "start": 1.0, "end": 6.0},
    ])
    # 6.0s at 30fps = 180 frames; a take of 179 frames is inside the tolerance.
    validate_measured_within_take(out, take_frames=179, fps=30)


def test_reconcile_document_refuses_a_real_take_that_is_too_short(tmp_path):
    """reconcile_document probes the live take and refuses to persist values
    that overrun it -- the wiring behind the pure-function guard."""
    import subprocess
    if subprocess.run(["which", "ffmpeg"], capture_output=True).returncode != 0:
        pytest.skip("ffmpeg not available")
    take = tmp_path / "take.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30",
        "-t", "3", "-pix_fmt", "yuv420p", str(take),
    ], capture_output=True, check=True)
    output = tmp_path / "production.yaml"
    output.write_text(yaml.safe_dump(document(), sort_keys=False))
    transcript = tmp_path / "overrun.json"
    # 6.0s of measured scenes against a 3s take.
    transcript.write_text(json.dumps({"segments": [
        {"start": 0, "end": 2, "text": "Hello world"},
        {"start": 2, "end": 6, "text": "Goodbye now"},
    ]}))
    with pytest.raises(ReconcileOverrunError):
        reconcile_document(output, transcript_json=transcript, take=take)
