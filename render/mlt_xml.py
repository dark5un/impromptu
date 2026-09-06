"""Generate deterministic MLT XML from a v2 production document.

Structure
---------
The presenter take is cut into scenes across two alternating playlists (A/B
roll) so that consecutive scenes can overlap for a transition.  A ``luma``
transition is emitted over each overlap; audio is summed with ``mix`` so the
overlap does not silence the voice.  That programme tractor is then composited
with the overlay track.

Compositing service
-------------------
``affine`` is used rather than ``qtblend``.  Verified on MLT 7.36.1 with a
ProRes 4444 ``yuva444p10le`` board over a video presenter: ``qtblend`` renders
either the board or the presenter but never both (``compositing=0`` drops the
lower track, ``compositing=1`` drops the board's alpha), whereas ``affine``
composites the alpha correctly.  ``affine``'s ``rect`` opacity field is a
*percentage* (``:100%``), not the 0..1 scale.  See docs/decisions.md.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

# Scene-relative geometry for a corner presenter inset, as x/y:WxH:opacity.
# affine reads opacity as a percentage; ":1" would render it ~invisible.
PIP_RECT = "70%/68%:25%x25%:100%"
FULLSCREEN_RECT = "0%/0%:100%x100%:100%"

# Transitions that need a grayscale luma map, mapped to the map generated into
# the production's cache.  A plain dissolve deliberately has no map: MLT's luma
# transition performs a cross-dissolve when `resource` is absent.
WIPE_MAPS = {"wipeleft": "linear_x.pgm", "wiperight": "linear_x_reverse.pgm"}


def _frame(seconds: float, fps: float) -> int:
    return round(seconds * fps)


def _duration(scene: dict[str, Any]) -> float:
    return float(scene.get("measured_sec") or scene["planned_sec"])


def scene_layout(document: dict[str, Any]) -> list[dict[str, Any]]:
    """Resolve every scene's programme position, take offset, and treatment.

    Returned per scene:
      ``take_start``        in-point in the continuous presenter recording
      ``duration``          scene length in seconds
      ``program_start``     position on the output timeline (overlaps applied)
      ``transition_frames`` overlap with the previous scene, in frames
      ``pip_rect``          affine rect when the presenter is an inset, else None
    """
    target = document["target"]
    fps = float(target["fps"])
    scenes = document["scenes"]
    layout: list[dict[str, Any]] = []
    take_cursor = 0.0
    program_cursor = 0.0
    for index, scene in enumerate(scenes):
        duration = _duration(scene)
        transition = scene.get("transition") or {}
        kind = transition.get("type") or "cut"
        requested = 0.0 if index == 0 or kind == "cut" else float(transition.get("dur") or 0.0)
        # An overlap can never exceed either neighbouring scene, or the
        # programme would run backwards.
        limit = min(duration, _duration(scenes[index - 1])) if index else 0.0
        overlap = max(0.0, min(requested, limit))
        overlap_frames = _frame(overlap, fps)
        program_start = max(0.0, program_cursor - overlap) if index else 0.0
        presenter = scene.get("presenter") or "fullscreen"
        layout.append({
            "id": scene["id"],
            "take_start": take_cursor,
            "duration": duration,
            "program_start": program_start,
            "transition": kind,
            "transition_frames": overlap_frames,
            "presenter": presenter,
            "overlay": scene.get("overlay"),
            "pip_rect": PIP_RECT if presenter == "corner" else None,
        })
        take_cursor += duration
        program_cursor = program_start + duration
    return layout


def luma_map_path(name: str, cache: str | Path) -> Path:
    """Return the cached path for wipe map *name* without creating it."""
    return Path(cache) / name


def write_luma_map(name: str, cache: str | Path) -> Path:
    """Write the grayscale wipe map for *name*, returning its path.

    Fedora's ``mlt`` package ships no luma maps (Kdenlive's live inside a
    flatpak), so the gradient is generated with the stdlib and cached.  Called
    at render time; XML generation stays a pure function.
    """
    import struct

    destination = luma_map_path(name, cache)
    if destination.exists():
        return destination
    width = height = 64
    reverse = name.endswith("_reverse.pgm")
    values = range(width - 1, -1, -1) if reverse else range(width)
    row = b"".join(struct.pack(">H", int(65535 * x / (width - 1))) for x in values)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(b"P5\n%d %d\n65535\n" % (width, height) + row * height)
    return destination


def required_luma_maps(document: dict[str, Any]) -> set[str]:
    """Names of the wipe maps this document's transitions need at render time."""
    return {
        WIPE_MAPS[item["transition"]]
        for item in scene_layout(document)
        if item["transition_frames"] and item["transition"] in WIPE_MAPS
    }


def document_to_xml(
    document: dict[str, Any],
    root: str | Path = ".",
    *,
    boards: dict[str, Path] | None = None,
    require_boards: bool = False,
) -> ET.ElementTree:
    """Build the MLT project for *document*.

    ``boards`` maps a media name to its rendered alpha ``.mov``.  Board media
    must be substituted this way: MLT cannot decode the authored HTML.
    """
    target = document["target"]
    width, height = target["resolution"]
    fps = float(target["fps"])
    root_path = Path(root)
    resolved = boards or {}
    layout = scene_layout(document)

    mlt = ET.Element("mlt", {"LC_NUMERIC": "C", "version": "7.36.1", "profile": "impromptu"})
    ET.SubElement(mlt, "profile", {
        "description": "impromptu production", "width": str(width), "height": str(height),
        "progressive": "1", "sample_aspect_num": "1", "sample_aspect_den": "1",
        "display_aspect_num": str(width), "display_aspect_den": str(height),
        "frame_rate_num": str(int(fps)), "frame_rate_den": "1", "colorspace": "709",
    })

    presenter = ET.SubElement(mlt, "producer", {"id": "presenter"})
    ET.SubElement(presenter, "property", {"name": "resource"}).text = str(
        root_path / document["presenter"]["source"])

    for name, media in document["media"].items():
        if media.get("type") == "board":
            rendered = resolved.get(name)
            if rendered is None:
                if require_boards:
                    raise ValueError(
                        f"board {name!r} has not been rendered; run `impromptu boards` "
                        "after `impromptu reconcile` so a .mov exists for MLT"
                    )
                source = root_path / media["src"]
            else:
                source = Path(rendered)
        else:
            source = root_path / media["src"]
        producer = ET.SubElement(mlt, "producer", {"id": f"media-{name}"})
        ET.SubElement(producer, "property", {"name": "resource"}).text = str(source)

    # ── presenter A/B roll, so neighbouring scenes can overlap ──────────────
    playlists = {
        0: ET.SubElement(mlt, "playlist", {"id": "presenter-a"}),
        1: ET.SubElement(mlt, "playlist", {"id": "presenter-b"}),
    }
    filled = {0: 0, 1: 0}
    for index, item in enumerate(layout):
        track = index % 2
        playlist = playlists[track]
        start_frame = _frame(item["program_start"], fps)
        if start_frame > filled[track]:
            ET.SubElement(playlist, "blank", {"length": str(start_frame - filled[track])})
        in_frame = _frame(item["take_start"], fps)
        length = _frame(item["duration"], fps)
        ET.SubElement(playlist, "entry", {
            "producer": "presenter", "in": str(in_frame), "out": str(in_frame + length - 1),
        })
        filled[track] = start_frame + length

    program = ET.SubElement(mlt, "tractor", {"id": "presenter-program", "global_feed": "1"})
    ET.SubElement(program, "track", {"producer": "presenter-a"})
    ET.SubElement(program, "track", {"producer": "presenter-b"})
    cache = root_path / ".cache" / "lumas"
    for index, item in enumerate(layout):
        if not item["transition_frames"]:
            continue
        start = _frame(item["program_start"], fps)
        transition = ET.SubElement(program, "transition", {
            "id": f"trans-{item['id']}",
            "in": str(start), "out": str(start + item["transition_frames"] - 1),
        })
        ET.SubElement(transition, "property", {"name": "mlt_service"}).text = "luma"
        # a_track is the outgoing scene's playlist, b_track the incoming one
        ET.SubElement(transition, "property", {"name": "a_track"}).text = str((index - 1) % 2)
        ET.SubElement(transition, "property", {"name": "b_track"}).text = str(index % 2)
        ET.SubElement(transition, "property", {"name": "progressive"}).text = "1"
        wipe = WIPE_MAPS.get(item["transition"])
        if wipe:
            ET.SubElement(transition, "property", {"name": "resource"}).text = str(
                luma_map_path(wipe, cache))
            ET.SubElement(transition, "property", {"name": "softness"}).text = "0.1"
    audio = ET.SubElement(program, "transition", {"id": "presenter-audio"})
    ET.SubElement(audio, "property", {"name": "mlt_service"}).text = "mix"
    ET.SubElement(audio, "property", {"name": "a_track"}).text = "0"
    ET.SubElement(audio, "property", {"name": "b_track"}).text = "1"
    ET.SubElement(audio, "property", {"name": "sum"}).text = "1"

    # ── overlay tracks, split by z-order ────────────────────────────────────
    # A board behind a `corner`/`hidden` presenter is the BED: the presenter
    # insets into it, or vanishes for pure b-roll.  A board over a `fullscreen`
    # presenter is a TOP overlay (lower third, badge) and must not be covered.
    # One track cannot express both, which is why there are two.
    bed_items = [i for i in layout if i["overlay"] and i["presenter"] != "fullscreen"]
    top_items = [i for i in layout if i["overlay"] and i["presenter"] == "fullscreen"]

    def _overlay_track(name: str, items: list[dict[str, Any]]) -> bool:
        if not items:
            return False
        playlist = ET.SubElement(mlt, "playlist", {"id": name})
        filled_frames = 0
        for item in items:
            start_frame = _frame(item["program_start"], fps)
            if start_frame > filled_frames:
                ET.SubElement(playlist, "blank",
                              {"length": str(start_frame - filled_frames)})
            length = _frame(item["duration"], fps)
            ET.SubElement(playlist, "entry", {
                "producer": f"media-{item['overlay']}", "in": "0", "out": str(length - 1),
            })
            filled_frames = start_frame + length
        return True

    has_bed = _overlay_track("overlay-bed", bed_items)
    has_top = _overlay_track("overlay-top", top_items)

    main = ET.SubElement(mlt, "tractor", {"id": "main", "global_feed": "1"})
    if not has_bed and not has_top:
        ET.SubElement(main, "track", {"producer": "presenter-program"})
        ET.indent(mlt, space="  ")
        return ET.ElementTree(mlt)

    track_index = 0
    bed_track = top_track = None
    if has_bed:
        ET.SubElement(main, "track", {"producer": "overlay-bed"})
        bed_track = track_index
        track_index += 1
    ET.SubElement(main, "track", {"producer": "presenter-program"})
    presenter_track = track_index
    track_index += 1
    if has_top:
        ET.SubElement(main, "track", {"producer": "overlay-top"})
        top_track = track_index

    if has_bed:
        # Presenter composited over the bed: fullscreen unless this scene insets
        # or hides it.  Keyframes switch geometry at each scene boundary.
        keyframes = []
        for item in layout:
            frame = _frame(item["program_start"], fps)
            if item["presenter"] == "hidden":
                rect = f"{FULLSCREEN_RECT.rsplit(':', 1)[0]}:0%"
            elif item["pip_rect"]:
                rect = item["pip_rect"]
            else:
                rect = FULLSCREEN_RECT
            keyframes.append(f"{frame}|={rect}")
        composite = ET.SubElement(main, "transition", {"id": "presenter-composite"})
        ET.SubElement(composite, "property", {"name": "mlt_service"}).text = "affine"
        ET.SubElement(composite, "property", {"name": "a_track"}).text = str(bed_track)
        ET.SubElement(composite, "property", {"name": "b_track"}).text = str(presenter_track)
        ET.SubElement(composite, "property", {"name": "rect"}).text = ";".join(keyframes)
        ET.SubElement(composite, "property", {"name": "fill"}).text = "1"
        ET.SubElement(composite, "property", {"name": "distort"}).text = "0"
        bed_audio = ET.SubElement(main, "transition", {"id": "overlay-bed-audio"})
        ET.SubElement(bed_audio, "property", {"name": "mlt_service"}).text = "mix"
        ET.SubElement(bed_audio, "property", {"name": "a_track"}).text = str(bed_track)
        ET.SubElement(bed_audio, "property", {"name": "b_track"}).text = str(presenter_track)
        ET.SubElement(bed_audio, "property", {"name": "sum"}).text = "1"

    if has_top:
        # Straight alpha composite of the graphic over whatever is below it.
        over = ET.SubElement(main, "transition", {"id": "overlay-top-composite"})
        ET.SubElement(over, "property", {"name": "mlt_service"}).text = "affine"
        ET.SubElement(over, "property", {"name": "a_track"}).text = str(presenter_track)
        ET.SubElement(over, "property", {"name": "b_track"}).text = str(top_track)
        ET.SubElement(over, "property", {"name": "rect"}).text = FULLSCREEN_RECT
        ET.SubElement(over, "property", {"name": "fill"}).text = "1"
        ET.SubElement(over, "property", {"name": "distort"}).text = "0"
        top_audio = ET.SubElement(main, "transition", {"id": "overlay-top-audio"})
        ET.SubElement(top_audio, "property", {"name": "mlt_service"}).text = "mix"
        ET.SubElement(top_audio, "property", {"name": "a_track"}).text = str(presenter_track)
        ET.SubElement(top_audio, "property", {"name": "b_track"}).text = str(top_track)
        ET.SubElement(top_audio, "property", {"name": "sum"}).text = "1"

    ET.indent(mlt, space="  ")
    return ET.ElementTree(mlt)


def write_mlt(document: dict[str, Any], destination: str | Path, root: str | Path = ".",
              *, boards: dict[str, Path] | None = None,
              require_boards: bool = False) -> Path:
    """Write the MLT project and materialise any wipe maps it references."""
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    cache = Path(root) / ".cache" / "lumas"
    for name in required_luma_maps(document):
        write_luma_map(name, cache)
    tree = document_to_xml(document, root, boards=boards, require_boards=require_boards)
    tree.write(path, encoding="utf-8", xml_declaration=True)
    return path


__all__ = [
    "FULLSCREEN_RECT",
    "PIP_RECT",
    "WIPE_MAPS",
    "document_to_xml",
    "luma_map_path",
    "required_luma_maps",
    "scene_layout",
    "write_luma_map",
    "write_mlt",
]
