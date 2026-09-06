"""Reconcile transcript timings with scenes in a production document."""
from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

from .document import load_document


def _seconds(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", ".")
    parts = text.split(":")
    if len(parts) == 1:
        return float(parts[0])
    if len(parts) == 3:
        return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
    raise ValueError(f"invalid transcript timestamp: {value!r}")


def _segments(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("segments", payload.get("transcription", []))
    result = []
    for item in raw:
        stamps = item.get("timestamps", {})
        start = item.get("start", stamps.get("from"))
        end = item.get("end", stamps.get("to"))
        if start is None or end is None:
            continue
        result.append({"text": str(item.get("text", "")).strip(),
                       "start": _seconds(start), "end": _seconds(end)})
    return [item for item in result if item["end"] > item["start"]]


def load_transcript(path: str | Path) -> list[dict[str, Any]]:
    return _segments(json.loads(Path(path).read_text()))


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9']+", text.lower()))


def _assign(doc: dict[str, Any], transcript: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    assigned = [[] for _ in doc["scenes"]]
    cursor = 0
    for segment in transcript:
        segment_words = _words(segment["text"])
        scores = []
        for index, scene in enumerate(doc["scenes"]):
            score = len(segment_words & _words(scene["say"]))
            scores.append(score if index >= cursor else -1)
        best = max(scores, default=-1)
        if best > 0:
            cursor = scores.index(best)
        else:
            planned_cursor = sum(float(s["planned_sec"]) for s in doc["scenes"][:cursor])
            while cursor + 1 < len(doc["scenes"]) and segment["start"] >= planned_cursor + float(doc["scenes"][cursor]["planned_sec"]):
                planned_cursor += float(doc["scenes"][cursor]["planned_sec"])
                cursor += 1
        assigned[cursor].append(segment)
    return assigned


def reconcile_data(doc: dict[str, Any], transcript: Iterable[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    transcript = list(transcript)
    assigned = _assign(doc, transcript)
    drift = []
    scene_start = 0.0
    for index, (scene, items) in enumerate(zip(doc["scenes"], assigned)):
        planned = float(scene["planned_sec"])
        if items:
            measured = max(item["end"] for item in items) - scene_start
            scene["measured_sec"] = round(measured, 6)
            scene["segments"] = [{"text": item["text"], "start": round(item["start"] - scene_start, 6),
                                  "end": round(item["end"] - scene_start, 6)} for item in items]
            scene_start = max(item["end"] for item in items)
        else:
            scene["measured_sec"] = planned
            scene["segments"] = []
            scene_start += planned
        drift.append({"scene": scene["id"], "planned_sec": planned,
                      "measured_sec": scene["measured_sec"],
                      "delta_sec": round(scene["measured_sec"] - planned, 6)})
    return doc, drift


def _run_whisper(command: list[str], take: str | Path | None) -> list[dict[str, Any]]:
    argv = list(command) + ([str(take)] if take is not None else [])
    completed = subprocess.run(argv, capture_output=True, text=True, check=True)
    return _segments(json.loads(completed.stdout))


def reconcile_document(path: str | Path, *, transcript_json: str | Path | None = None,
                       take: str | Path | None = None,
                       whisper_command: list[str] | None = None) -> dict[str, Any]:
    """Update *path* from fixture JSON or a whisper.cpp JSON-producing command."""
    doc = load_document(path)
    if transcript_json is not None:
        transcript = load_transcript(transcript_json)
    elif whisper_command is not None:
        transcript = _run_whisper(whisper_command, take)
    else:
        raise ValueError("provide transcript_json or whisper_command")
    doc, drift = reconcile_data(doc, transcript)
    Path(path).write_text(yaml.safe_dump(doc, sort_keys=False))
    result = dict(doc)
    result["drift"] = drift
    return result


__all__ = ["load_transcript", "reconcile_data", "reconcile_document"]
