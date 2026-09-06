"""Convert the v1 script and scene plan into a v2 production document."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml


def _slug(value: str, fallback: str) -> str:
    result = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return result or fallback


def _script_sections(path: Path) -> tuple[str, list[str]]:
    lines = path.read_text().splitlines()
    title = path.stem.replace("-", " ").title()
    sections: list[tuple[str, list[str]]] = []
    current: list[str] | None = None
    for line in lines:
        if line.startswith("# "):
            title = line[2:].strip() or title
        elif line.startswith("## "):
            current = []
            sections.append((line[3:].strip(), current))
        elif current is not None:
            current.append(line)
    if not sections:
        body = "\n".join(line for line in lines if not line.startswith("#")).strip()
        sections = [("Scene 1", [body])]
    texts = ["\n".join(part).strip() for _, part in sections]
    return title, texts


def _graphic_sources(plan: dict[str, Any]) -> list[Any]:
    for key in ("graphics", "graphic_files", "media"):
        value = plan.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            return list(value.values())
    return []


def _media_entry(source: Any) -> tuple[str, dict[str, str]]:
    if isinstance(source, dict):
        src = source.get("src", source.get("path", source.get("file")))
        media_type = source.get("type")
    else:
        src, media_type = source, None
    if not isinstance(src, str) or not src:
        raise ValueError(f"invalid graphic media entry: {source!r}")
    if media_type not in {"board", "video"}:
        media_type = "board" if Path(src).suffix.lower() in {".html", ".htm"} else "video"
    return src, {"type": media_type, "src": src}


def migrate_v1(script_path: str | Path, scene_plan_path: str | Path,
               output_path: str | Path | None = None) -> dict[str, Any]:
    """Return a validated v2 document converted from v1 files."""
    script = Path(script_path)
    plan_path = Path(scene_plan_path)
    plan = json.loads(plan_path.read_text())
    title, script_texts = _script_sections(script)
    sources = _graphic_sources(plan)
    media: dict[str, dict[str, str]] = {}
    for index, source in enumerate(sources):
        _src, entry = _media_entry(source)
        media[f"graphic-{index + 1}"] = entry

    scenes = []
    for index, old in enumerate(plan.get("scenes", [])):
        start = float(old.get("start_sec", 0))
        end = float(old.get("end_sec", start))
        if end <= start:
            raise ValueError(f"scene {index} must have a positive duration")
        graphic = old.get("graphic")
        overlay = None
        if graphic is not None:
            if not isinstance(graphic, int) or graphic < 0 or graphic >= len(sources):
                raise ValueError(f"graphic index {graphic!r} is not present in v1 media")
            overlay = f"graphic-{graphic + 1}"
        mode = old.get("mode", "fullscreen")
        presenter = {"fullscreen": "fullscreen", "corner": "corner", "bg_only": "hidden"}.get(mode, mode)
        if presenter not in {"fullscreen", "corner", "hidden"}:
            presenter = "fullscreen"
        scene_title = str(old.get("title", f"Scene {index + 1}"))
        say = script_texts[index] if index < len(script_texts) else ""
        if not say:
            raise ValueError(f"scene {index} has no script text")
        scenes.append({
            "id": _slug(scene_title, f"scene-{index + 1}"), "say": say,
            "planned_sec": end - start, "measured_sec": None, "segments": None,
            "presenter": presenter, "overlay": overlay,
            "transition": {"type": "cut", "dur": 0.0},
        })
    if not scenes:
        raise ValueError("v1 scene plan has no scenes")
    target = plan.get("orientation", "landscape")
    resolution = [1080, 1920] if target == "vertical" else [1920, 1080]
    document = {
        "schema": 1, "title": title,
        "target": {"orientation": target, "resolution": plan.get("resolution", resolution),
                    "fps": plan.get("fps", 30)},
        "media": media,
        "presenter": {"source": plan.get("presenter", "takes/presenter.mp4")},
        "scenes": scenes,
    }
    if output_path is not None:
        Path(output_path).write_text(yaml.safe_dump(document, sort_keys=False))
    return document


__all__ = ["migrate_v1"]
