"""Generate deterministic MLT XML from a v2 production document."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


def _frame(seconds: float, fps: float) -> int:
    return round(seconds * fps)


def document_to_xml(document: dict[str, Any], root: str | Path = ".") -> ET.ElementTree:
    target = document["target"]
    width, height = target["resolution"]
    fps = target["fps"]
    scenes = document["scenes"]
    mlt = ET.Element("mlt", {"LC_NUMERIC": "C", "version": "7.36.1", "profile": "impromptu"})
    ET.SubElement(mlt, "profile", {
        "description": "impromptu production", "width": str(width), "height": str(height),
        "progressive": "1", "sample_aspect_num": "1", "sample_aspect_den": "1",
        "display_aspect_num": str(width), "display_aspect_den": str(height),
        "frame_rate_num": str(fps), "frame_rate_den": "1", "colorspace": "709",
    })
    presenter = ET.SubElement(mlt, "producer", {"id": "presenter"})
    ET.SubElement(presenter, "property", {"name": "resource"}).text = str(Path(root) / document["presenter"]["source"])
    for name, media in document["media"].items():
        producer = ET.SubElement(mlt, "producer", {"id": f"media-{name}"})
        ET.SubElement(producer, "property", {"name": "resource"}).text = str(Path(root) / media["src"])

    presenter_playlist = ET.SubElement(mlt, "playlist", {"id": "presenter-track"})
    cursor = 0.0
    for scene in scenes:
        duration = float(scene.get("measured_sec") or scene["planned_sec"])
        ET.SubElement(presenter_playlist, "entry", {
            "producer": "presenter", "in": str(_frame(cursor, fps)),
            "out": str(_frame(cursor + duration, fps) - 1),
        })
        cursor += duration

    overlay_playlist = ET.SubElement(mlt, "playlist", {"id": "overlay-track"})
    cursor = 0.0
    has_overlay = False
    for scene in scenes:
        duration = float(scene.get("measured_sec") or scene["planned_sec"])
        overlay = scene.get("overlay")
        if overlay:
            if cursor:
                ET.SubElement(overlay_playlist, "blank", {"length": str(_frame(cursor, fps))})
            ET.SubElement(overlay_playlist, "entry", {
                "producer": f"media-{overlay}", "in": "0",
                "out": str(_frame(duration, fps) - 1),
            })
            has_overlay = True
        cursor += duration

    tractor = ET.SubElement(mlt, "tractor", {"id": "main", "global_feed": "1"})
    ET.SubElement(tractor, "track", {"producer": "presenter-track"})
    if has_overlay:
        ET.SubElement(tractor, "track", {"producer": "overlay-track"})
        transition = ET.SubElement(tractor, "transition", {"id": "overlay-composite"})
        ET.SubElement(transition, "property", {"name": "mlt_service"}).text = "qtblend"
        ET.SubElement(transition, "property", {"name": "a_track"}).text = "0"
        ET.SubElement(transition, "property", {"name": "b_track"}).text = "1"
        ET.SubElement(transition, "property", {"name": "compositing"}).text = "1"
        audio = ET.SubElement(tractor, "transition", {"id": "audio-mix"})
        ET.SubElement(audio, "property", {"name": "mlt_service"}).text = "mix"
        ET.SubElement(audio, "property", {"name": "a_track"}).text = "0"
        ET.SubElement(audio, "property", {"name": "b_track"}).text = "1"
        ET.SubElement(audio, "property", {"name": "sum"}).text = "1"
    ET.indent(mlt, space="  ")
    return ET.ElementTree(mlt)


def write_mlt(document: dict[str, Any], destination: str | Path, root: str | Path = ".") -> Path:
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    document_to_xml(document, root).write(path, encoding="utf-8", xml_declaration=True)
    return path


__all__ = ["document_to_xml", "write_mlt"]
