"""Deterministic editorial decisions for a reconciled production document.

`direct` fills only fields the author has left ``null``.  A decided value is
never overwritten, because the plan's review step ("skim the document, change
anything you disagree with") is only meaningful if your edits survive the next
`direct` run.  Pass ``force=True`` to deliberately re-decide every scene.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

_TRANSITION = {"type": "dissolve", "dur": 0.4}
_CUT = {"type": "cut", "dur": 0.0}


def decide_presenter(scene: dict[str, Any], media: dict[str, Any]) -> str:
    """Choose the presenter treatment from what the scene is showing."""
    overlay = scene.get("overlay")
    if overlay is None:
        return "fullscreen"
    if media.get(overlay, {}).get("type") == "video":
        return "hidden"
    return "corner"


def decide_scene(scene: dict[str, Any], media: dict[str, Any], *, first: bool = False,
                 force: bool = False) -> dict[str, Any]:
    """Return one scene with presenter treatment and a conservative transition."""
    result = deepcopy(scene)
    if force or result.get("presenter") is None:
        result["presenter"] = decide_presenter(result, media)
    if force or result.get("transition") is None:
        result["transition"] = deepcopy(_CUT if first else _TRANSITION)
    return result


def direct_document(document: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
    """Apply directorial defaults without mutating *document*.

    Only ``null`` presenter/transition fields are decided unless *force* is set;
    every other field, including human overrides, is preserved verbatim.
    """
    result = deepcopy(document)
    media = result.get("media", {})
    result["scenes"] = [
        decide_scene(scene, media, first=index == 0, force=force)
        for index, scene in enumerate(result.get("scenes", []))
    ]
    return result


def direct_production(path: str | Path, *, force: bool = False) -> dict[str, Any]:
    """Load, direct, and write a production YAML document."""
    from .document import validate_document

    source = Path(path)
    document = direct_document(yaml.safe_load(source.read_text()), force=force)
    errors = validate_document(document)
    if errors:
        raise ValueError("invalid directed document: " + "; ".join(errors))
    source.write_text(yaml.safe_dump(document, sort_keys=False))
    return document


__all__ = ["decide_presenter", "decide_scene", "direct_document", "direct_production"]
