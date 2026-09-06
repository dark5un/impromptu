"""Deterministic editorial decisions for a reconciled production document."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

_TRANSITION = {"type": "dissolve", "dur": 0.4}
_CUT = {"type": "cut", "dur": 0.0}


def decide_scene(scene: dict[str, Any], media: dict[str, Any], *, first: bool = False) -> dict[str, Any]:
    """Return one scene with presenter treatment and a conservative transition."""
    result = deepcopy(scene)
    overlay = result.get("overlay")
    if overlay is None:
        result["presenter"] = "fullscreen"
    elif media.get(overlay, {}).get("type") == "video":
        result["presenter"] = "hidden"
    else:
        result["presenter"] = "corner"
    result["transition"] = deepcopy(_CUT if first else _TRANSITION)
    return result


def direct_document(document: dict[str, Any]) -> dict[str, Any]:
    """Apply directorial defaults without mutating *document*.

    Overlay media names are already resolved by document validation; this function
    only decides presentation, transition grammar, and preserves all other edits.
    """
    result = deepcopy(document)
    media = result.get("media", {})
    result["scenes"] = [
        decide_scene(scene, media, first=index == 0)
        for index, scene in enumerate(result.get("scenes", []))
    ]
    return result


def direct_production(path: str | Path) -> dict[str, Any]:
    """Load, direct, and write a production YAML document."""
    from .document import validate_document

    source = Path(path)
    document = direct_document(yaml.safe_load(source.read_text()))
    errors = validate_document(document)
    if errors:
        raise ValueError("invalid directed document: " + "; ".join(errors))
    source.write_text(yaml.safe_dump(document, sort_keys=False))
    return document


__all__ = ["decide_scene", "direct_document", "direct_production"]
