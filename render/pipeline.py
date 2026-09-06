"""Production-document render and packaging orchestration."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from core.direct import direct_document
from core.document import load_document, validate_document
from render.melt import run_melt
from render.mlt_xml import write_mlt


def _production_path(directory: str | Path) -> Path:
    path = Path(directory)
    return path if path.is_file() else path / "production.yaml"


def _load_directed(source: Path) -> dict[str, Any]:
    """Load a production file, applying the directorial defaults first."""
    # load_document deliberately rejects the pre-directing null fields.  Rendering
    # is the first consumer that needs those fields, so direct before validation.
    raw = yaml.safe_load(source.read_text())
    document = direct_document(raw)
    errors = validate_document(document)
    if errors:
        # Reuse the document loader's established error formatting for malformed
        # files while preserving FileNotFoundError from the read above.
        return load_document(source)
    return document


def render_production(
    directory: str | Path,
    *,
    runner: Callable[..., Any] = run_melt,
    threads: int = 1,
) -> Path:
    """Render ``production.yaml`` to ``out/master.mp4`` and return its path."""
    source = _production_path(directory)
    document = _load_directed(source)
    root = source.parent
    out = root / "out"
    out.mkdir(parents=True, exist_ok=True)
    project = out / "production.mlt"
    write_mlt(document, project, root)
    master = out / "master.mp4"
    runner(project, master, threads=threads)
    return master


def _timestamp(seconds: float) -> str:
    total = int(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def _chapters(document: dict[str, Any]) -> str:
    lines: list[str] = []
    cursor = 0.0
    for scene in document["scenes"]:
        lines.append(f"{_timestamp(cursor)} {scene['id']}")
        cursor += float(scene.get("measured_sec") or scene["planned_sec"])
    return "\n".join(lines) + "\n"


def _checklist(title: str) -> str:
    return (f"# Upload checklist — {title}\n\n"
            "- [ ] Review master audio and scene boundaries\n"
            "- [ ] Review thumbnail and description\n"
            "- [ ] Upload manually (impromptu NEVER uploads)\n")


def package_production(
    directory: str | Path,
    *,
    runner: Callable[..., Any] | None = None,
) -> dict[str, Path]:
    """Create loudness-normalised master and document-derived package files."""
    source = _production_path(directory)
    document = _load_directed(source)
    root = source.parent
    out = root / "out"
    master = out / "master.mp4"
    if not master.exists():
        raise FileNotFoundError(f"render output is missing: {master}")
    out.mkdir(parents=True, exist_ok=True)
    loud = out / "master-loudnorm.mp4"
    chapters = out / "chapters.txt"
    description = out / "description.md"
    thumbnail = out / "thumbnail.png"
    checklist = out / "upload-checklist.md"
    command_runner = runner
    if command_runner is None:
        import subprocess
        command_runner = subprocess.run
    command_runner(["ffmpeg", "-y", "-i", str(master), "-af",
                    "loudnorm=I=-14:TP=-1.5:LRA=11", str(loud)], check=True)
    command_runner(["ffmpeg", "-y", "-i", str(master), "-frames:v", "1",
                    "-vf", "scale=1280:720", "-metadata", "thumbnail=1",
                    str(thumbnail)], check=True)
    chapters.write_text(_chapters(document))
    description.write_text(f"# {document['title']}\n\nSee chapters.txt for chapter markers.\n")
    checklist.write_text(_checklist(document["title"]))
    return {"master": loud, "chapters": chapters, "description": description,
            "thumbnail": thumbnail, "checklist": checklist}


__all__ = ["package_production", "render_production"]
