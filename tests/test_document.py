import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.document import (
    DocumentError,
    load_document,
    patch_document,
    validate_document,
)


def valid_document():
    return {
        "schema": 1,
        "title": "Demo",
        "target": {"orientation": "landscape", "resolution": [1920, 1080], "fps": 30},
        "media": {"drift": {"type": "board", "src": "boards/drift.html"}},
        "presenter": {"source": "takes/take.mp4"},
        "scenes": [{"id": "intro", "say": "Hello", "planned_sec": 2.0,
                    "measured_sec": None, "segments": None, "presenter": "fullscreen",
                    "overlay": None, "transition": {"type": "cut", "dur": 0.0}}],
    }


def test_pre_directing_null_scene_fields_are_valid(tmp_path):
    doc = valid_document()
    doc["scenes"][0]["presenter"] = None
    doc["scenes"][0]["overlay"] = None
    doc["scenes"][0]["transition"] = None
    assert validate_document(doc) == []


def test_valid_document_loads_and_normalizes(tmp_path):
    path = tmp_path / "production.yaml"
    path.write_text("schema: 1\ntitle: Demo\ntarget:\n  orientation: landscape\n  resolution: [1920, 1080]\n  fps: 30\nmedia: {}\npresenter:\n  source: takes/take.mp4\nscenes:\n  - id: intro\n    say: Hello\n    planned_sec: 2\n    measured_sec: null\n    segments: null\n    presenter: fullscreen\n    overlay: null\n    transition: {type: cut, dur: 0}\n")
    doc = load_document(path)
    assert doc["schema"] == 1
    assert validate_document(doc) == []


def test_unknown_top_level_key_is_rejected():
    doc = valid_document()
    doc["surprise"] = True
    errors = validate_document(doc)
    assert any("surprise" in error for error in errors)


def test_overlay_must_resolve_named_media():
    doc = valid_document()
    doc["scenes"][0]["overlay"] = "missing"
    errors = validate_document(doc)
    assert any("missing" in error for error in errors)


def test_scene_segments_must_be_contiguous():
    doc = valid_document()
    doc["scenes"][0]["measured_sec"] = 2.0
    doc["scenes"][0]["segments"] = [{"text": "Hello", "start": 0.0, "end": 0.5},
                                    {"text": "again", "start": 0.7, "end": 2.0}]
    errors = validate_document(doc)
    assert any("contiguous" in error for error in errors)


def test_patch_updates_document_and_writes_yaml(tmp_path):
    path = tmp_path / "production.yaml"
    import yaml
    path.write_text(yaml.safe_dump(valid_document(), sort_keys=False))
    patch_document(path, {"title": "Updated"})
    assert load_document(path)["title"] == "Updated"


def test_invalid_document_raises_with_errors(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("schema: 2\n")
    with pytest.raises(DocumentError, match="schema"):
        load_document(path)


def test_patch_rejects_unknown_path(tmp_path):
    path = tmp_path / "production.yaml"
    import yaml
    path.write_text(yaml.safe_dump(valid_document(), sort_keys=False))
    with pytest.raises(DocumentError, match="unknown"):
        patch_document(path, {"nope.value": 1})
