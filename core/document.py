"""Load, validate, and patch the v2 production document."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


class DocumentError(ValueError):
    """Raised when a production document cannot be loaded or validated."""


TOP_LEVEL = {"schema", "title", "target", "media", "presenter", "scenes"}
TARGET_KEYS = {"orientation", "resolution", "fps"}
MEDIA_KEYS = {"type", "src"}
PRESENTER_KEYS = {"source"}
SCENE_KEYS = {"id", "say", "planned_sec", "measured_sec", "segments", "presenter", "overlay", "transition"}
TRANSITION_KEYS = {"type", "dur"}
MEDIA_TYPES = {"board", "video"}
ORIENTATIONS = {"landscape": (1920, 1080), "vertical": (1080, 1920)}
PRESENTER_MODES = {"fullscreen", "corner", "hidden"}
TRANSITIONS = {"cut", "dissolve", "wipeleft", "wiperight"}


def _mapping(value: Any, where: str, errors: list[str]) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        errors.append(f"{where} must be a mapping")
        return None
    return value


def _unknown(mapping: dict[str, Any], allowed: set[str], where: str, errors: list[str]) -> None:
    for key in sorted(set(mapping) - allowed):
        errors.append(f"{where}: unknown key {key!r}")


def validate_document(doc: Any) -> list[str]:
    errors: list[str] = []
    root = _mapping(doc, "document", errors)
    if root is None:
        return errors
    _unknown(root, TOP_LEVEL, "document", errors)
    if root.get("schema") != 1:
        errors.append("document.schema must be 1")
    if not isinstance(root.get("title"), str) or not root["title"].strip():
        errors.append("document.title must be a non-empty string")

    target = _mapping(root.get("target"), "target", errors)
    if target:
        _unknown(target, TARGET_KEYS, "target", errors)
        orientation = target.get("orientation")
        if orientation not in ORIENTATIONS:
            errors.append("target.orientation must be landscape or vertical")
        resolution = target.get("resolution")
        expected = list(ORIENTATIONS[orientation]) if orientation in ORIENTATIONS else None
        if resolution != expected:
            errors.append("target.resolution must match target.orientation")
        if not isinstance(target.get("fps"), (int, float)) or target["fps"] <= 0:
            errors.append("target.fps must be a positive number")

    media = _mapping(root.get("media"), "media", errors)
    if media is not None:
        for name, item in media.items():
            if not isinstance(name, str) or not name:
                errors.append("media names must be non-empty strings")
                continue
            entry = _mapping(item, f"media.{name}", errors)
            if entry:
                _unknown(entry, MEDIA_KEYS, f"media.{name}", errors)
                if entry.get("type") not in MEDIA_TYPES:
                    errors.append(f"media.{name}.type must be board or video")
                if not isinstance(entry.get("src"), str) or not entry["src"]:
                    errors.append(f"media.{name}.src must be a non-empty string")

    presenter = _mapping(root.get("presenter"), "presenter", errors)
    if presenter:
        _unknown(presenter, PRESENTER_KEYS, "presenter", errors)
        if not isinstance(presenter.get("source"), str) or not presenter["source"]:
            errors.append("presenter.source must be a non-empty string")

    scenes = root.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        errors.append("scenes must be a non-empty list")
        return errors
    previous_end = 0.0
    for index, scene_value in enumerate(scenes):
        where = f"scenes[{index}]"
        scene = _mapping(scene_value, where, errors)
        if scene is None:
            continue
        _unknown(scene, SCENE_KEYS, where, errors)
        for key in ("id", "say"):
            if not isinstance(scene.get(key), str) or not scene[key].strip():
                errors.append(f"{where}.{key} must be a non-empty string")
        if not isinstance(scene.get("planned_sec"), (int, float)) or scene["planned_sec"] <= 0:
            errors.append(f"{where}.planned_sec must be positive")
        measured = scene.get("measured_sec")
        if measured is not None and (not isinstance(measured, (int, float)) or measured <= 0):
            errors.append(f"{where}.measured_sec must be positive or null")
        segments = scene.get("segments")
        if segments is not None and not isinstance(segments, list):
            errors.append(f"{where}.segments must be a list or null")
        if isinstance(segments, list):
            cursor = 0.0
            for segment_index, segment_value in enumerate(segments):
                segment = _mapping(segment_value, f"{where}.segments[{segment_index}]", errors)
                if segment is None:
                    continue
                for key in ("text", "start", "end"):
                    if key not in segment:
                        errors.append(f"{where}.segments[{segment_index}] missing {key}")
                if isinstance(segment.get("start"), (int, float)) and abs(segment["start"] - cursor) > 1e-6:
                    errors.append(f"{where}.segments are not contiguous")
                if isinstance(segment.get("start"), (int, float)) and isinstance(segment.get("end"), (int, float)):
                    if segment["end"] <= segment["start"]:
                        errors.append(f"{where}.segments[{segment_index}] end must exceed start")
                    cursor = float(segment["end"])
            if isinstance(measured, (int, float)) and segments and abs(cursor - measured) > 1e-6:
                errors.append(f"{where}.segments must end at measured_sec")
        if scene.get("presenter") not in PRESENTER_MODES:
            errors.append(f"{where}.presenter must be fullscreen, corner, or hidden")
        overlay = scene.get("overlay")
        if overlay is not None and overlay not in (media or {}):
            errors.append(f"{where}.overlay {overlay!r} does not resolve to media")
        transition = _mapping(scene.get("transition"), f"{where}.transition", errors)
        if transition:
            _unknown(transition, TRANSITION_KEYS, f"{where}.transition", errors)
            if transition.get("type") not in TRANSITIONS:
                errors.append(f"{where}.transition.type is invalid")
            if not isinstance(transition.get("dur"), (int, float)) or transition["dur"] < 0:
                errors.append(f"{where}.transition.dur must be non-negative")
        previous_end += float(scene.get("planned_sec", 0))
    return errors


def load_document(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        doc = yaml.safe_load(source.read_text())
    except (OSError, yaml.YAMLError) as exc:
        raise DocumentError(f"cannot read {source}: {exc}") from exc
    errors = validate_document(doc)
    if errors:
        raise DocumentError("invalid production document:\n" + "\n".join(f"- {error}" for error in errors))
    return doc


def patch_document(path: str | Path, changes: dict[str, Any]) -> dict[str, Any]:
    doc = load_document(path)
    updated = deepcopy(doc)
    for dotted, value in changes.items():
        parts = dotted.split(".")
        cursor: Any = updated
        for part in parts[:-1]:
            if not isinstance(cursor, dict) or part not in cursor:
                raise DocumentError(f"unknown patch path {dotted!r}")
            cursor = cursor[part]
        if not isinstance(cursor, dict) or parts[-1] not in cursor:
            raise DocumentError(f"unknown patch path {dotted!r}")
        cursor[parts[-1]] = value
    errors = validate_document(updated)
    if errors:
        raise DocumentError("patch produces invalid document:\n" + "\n".join(f"- {error}" for error in errors))
    Path(path).write_text(yaml.safe_dump(updated, sort_keys=False))
    return updated


def planned_scene_ranges(doc: dict[str, Any]) -> list[tuple[float, float]]:
    cursor = 0.0
    ranges = []
    for scene in doc["scenes"]:
        end = cursor + float(scene["planned_sec"])
        ranges.append((cursor, end))
        cursor = end
    return ranges


__all__ = ["DocumentError", "load_document", "patch_document", "planned_scene_ranges", "validate_document"]
