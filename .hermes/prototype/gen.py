#!/usr/bin/env python3
"""Generate MLT XML from a scene plan. Stdlib only. Proves agent-authorability."""
import xml.etree.ElementTree as ET

FPS = 30
W, H = 1920, 1080

# The "document" the agent would write
SCENES = [
    {"id": "intro",       "start": 0.0,  "end": 10.0, "presenter": "fullscreen", "overlay": None,    "transition": None},
    {"id": "the-numbers", "start": 10.0, "end": 20.0, "presenter": "corner",     "overlay": "board", "transition": "wipe"},
    {"id": "outro",       "start": 20.0, "end": 30.0, "presenter": "fullscreen", "overlay": None,    "transition": "dissolve"},
]
PRESENTER = "presenter.mp4"
OVERLAYS = {"board": "board.mp4"}
PIP_RECT = "70%/68%:25%x25%"   # x/y:WxH  -- qtblend geometry


def f(sec):
    return int(round(sec * FPS))


def build():
    mlt = ET.Element("mlt", {"LC_NUMERIC": "C", "version": "7.36.1", "profile": "atsc_1080p_30"})
    ET.SubElement(mlt, "profile", {
        "description": "HD 1080p 30fps", "width": str(W), "height": str(H),
        "progressive": "1", "sample_aspect_num": "1", "sample_aspect_den": "1",
        "display_aspect_num": "16", "display_aspect_den": "9",
        "frame_rate_num": str(FPS), "frame_rate_den": "1", "colorspace": "709",
    })

    # --- producers ---
    p = ET.SubElement(mlt, "producer", {"id": "presenter"})
    ET.SubElement(p, "property", {"name": "resource"}).text = PRESENTER
    for name, path in OVERLAYS.items():
        o = ET.SubElement(mlt, "producer", {"id": f"ov_{name}"})
        ET.SubElement(o, "property", {"name": "resource"}).text = path

    # --- track 1: presenter, cut into scenes ---
    pl = ET.SubElement(mlt, "playlist", {"id": "presenter_track"})
    for sc in SCENES:
        ET.SubElement(pl, "entry", {
            "producer": "presenter",
            "in": str(f(sc["start"])),
            "out": str(f(sc["end"]) - 1),
        })

    # --- track 2: overlays, with blanks where there is nothing ---
    ov = ET.SubElement(mlt, "playlist", {"id": "overlay_track"})
    cursor = 0.0
    has_overlay = False
    for sc in SCENES:
        if sc["overlay"]:
            gap = sc["start"] - cursor
            if gap > 0:
                ET.SubElement(ov, "blank", {"length": str(f(gap))})
            dur = sc["end"] - sc["start"]
            ET.SubElement(ov, "entry", {
                "producer": f"ov_{sc['overlay']}",
                "in": "0", "out": str(f(dur) - 1),
            })
            cursor = sc["end"]
            has_overlay = True

    # --- tractor: combine tracks ---
    tr = ET.SubElement(mlt, "tractor", {"id": "main", "global_feed": "1"})
    ET.SubElement(tr, "track", {"producer": "presenter_track"})
    if has_overlay:
        ET.SubElement(tr, "track", {"producer": "overlay_track"})

        # board fullscreen-under, presenter shrunk to corner => composite presenter OVER board.
        # Simpler and equally valid: board as PiP over fullscreen presenter.
        t = ET.SubElement(tr, "transition", {"id": "pip"})
        ET.SubElement(t, "property", {"name": "mlt_service"}).text = "qtblend"
        ET.SubElement(t, "property", {"name": "a_track"}).text = "0"
        ET.SubElement(t, "property", {"name": "b_track"}).text = "1"
        ET.SubElement(t, "property", {"name": "rect"}).text = PIP_RECT
        ET.SubElement(t, "property", {"name": "compositing"}).text = "0"

        # audio must be mixed explicitly or the overlay track silences/overrides
        a = ET.SubElement(tr, "transition", {"id": "amix"})
        ET.SubElement(a, "property", {"name": "mlt_service"}).text = "mix"
        ET.SubElement(a, "property", {"name": "a_track"}).text = "0"
        ET.SubElement(a, "property", {"name": "b_track"}).text = "1"
        ET.SubElement(a, "property", {"name": "sum"}).text = "1"

    ET.indent(mlt, space="  ")
    return ET.ElementTree(mlt)


if __name__ == "__main__":
    build().write("project.mlt", encoding="utf-8", xml_declaration=True)
    print("wrote project.mlt")
