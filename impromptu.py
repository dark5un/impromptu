#!/usr/bin/env python3
"""
impromptu — terminal teleprompter + video compositor for
            human-presenter video production.

Subcommands:
  impromptu script.md       Teleprompter — scroll through script
  impromptu new script.md   Scaffold a sample script
  impromptu composite ...   Composite presenter + graphics into final video
"""

import argparse
import json
import os
import re
import select
import shutil
import subprocess
import sys
import termios
import time
import tty
from pathlib import Path


# ═══════════════════════════════════════════════════════════════════════
# TELEPROMPTER
# ═══════════════════════════════════════════════════════════════════════

def get_terminal_size():
    return shutil.get_terminal_size((80, 24))


def read_script(path):
    with open(path) as f:
        return [line.rstrip('\n') for line in f.readlines()]


def enable_raw_mode():
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    tty.setraw(fd)
    return old


def restore_raw_mode(old):
    if old:
        fd = sys.stdin.fileno()
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def run_teleprompter(lines, start_speed=1.5):
    old_tty = enable_raw_mode()
    try:
        _run(lines, start_speed)
    finally:
        restore_raw_mode(old_tty)


def _run(lines, start_speed):
    n = len(lines)
    idx = 0
    speed = start_speed
    paused = False
    last_tick = time.monotonic()

    def render():
        cols, rows = get_terminal_size()
        buf_lines = rows - 2
        half = buf_lines // 2
        start = max(0, idx - half)
        end = min(n, start + buf_lines)
        if end - start < buf_lines:
            start = max(0, end - buf_lines)

        out = []
        for i in range(start, end):
            line = lines[i]
            prefix = "▸ " if i == idx else "  "
            if i < idx:
                out.append(f"\033[2m{prefix}{line}\033[0m")
            elif i == idx:
                out.append(f"\033[97m{prefix}{line}\033[0m")
            else:
                out.append(f"\033[37m{prefix}{line}\033[0m")

        pct = int(idx / max(n - 1, 1) * 100)
        status = "⏸ PAUSED" if paused else "▶"
        hdr = f"\033[90m── impromptu [{status}] line {idx+1}/{n} ({pct}%) speed:{speed:.1f} ──\033[0m\n"
        ft = f"\n\033[90mSpace:pause ↑↓:move +/-:speed 0:top q:quit\033[0m"
        sys.stdout.write("\033[H" + hdr + "\n".join(out) + ft)
        sys.stdout.flush()

    render()
    while True:
        now = time.monotonic()
        dt = now - last_tick
        last_tick = now

        if not paused and speed > 0:
            advance = speed * dt
            if advance >= 0.5:
                idx = min(n - 1, idx + int(round(advance)))

        r, _, _ = select.select([sys.stdin], [], [], 0.05)
        if r:
            ch = sys.stdin.read(1)
            if ch in ('q', '\x04'):
                break
            elif ch == ' ':
                paused = not paused
            elif ch == '\x1b':
                more = sys.stdin.read(2)
                if more == '[A':
                    idx = max(0, idx - 1)
                elif more == '[B':
                    idx = min(n - 1, idx + 1)
                elif more == '[C':
                    idx = min(n - 1, idx + 5)
                elif more == '[D':
                    idx = max(0, idx - 5)
            elif ch == '+':
                speed = min(10.0, speed + 0.3)
            elif ch == '-':
                speed = max(0.3, speed - 0.3)
            elif ch == '0':
                idx = 0
            elif ch == '\r':
                paused = not paused

        render()

    sys.stdout.write("\033[H\033[J")
    sys.stdout.flush()


def cmd_prompter(args):
    path = args.script
    if not os.path.exists(path):
        print(f"❌ Script not found: {path}")
        sys.exit(1)
    lines = read_script(path)
    if not lines:
        print("❌ Empty script")
        sys.exit(1)
    try:
        run_teleprompter(lines, args.speed)
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\033[H\033[J\033[?25h")


def cmd_new(args):
    path = args.path or "script.md"
    if os.path.exists(path):
        print(f"❌ {path} already exists")
        sys.exit(1)
    content = """# My Video Script

## Introduction
Hi everyone, and welcome.

Today I want to talk about something exciting.

## Main Point
The key insight here is that simplicity wins.

When you build tools that are easy to use,
people actually use them.

## Data
Let me show you the numbers:

* 10x improvement in speed
* 50% reduction in cost
* 99.9% reliability

## Conclusion
So what does this mean for you?

It means you can achieve more with less effort.

Thanks for watching, and see you next time!
"""
    with open(path, "w") as f:
        f.write(content)
    print(f"✓ Scaffolded {path}")


# ═══════════════════════════════════════════════════════════════════════
# COMPOSITE — news-director style video compositor
# ═══════════════════════════════════════════════════════════════════════

def parse_framerate(fr):
    """Parse an ffprobe r_frame_rate string ("30/1", "30000/1001", "25").

    Returns 0.0 for zero denominators ("0/0") or unparseable input —
    never raises, unlike the old eval()-based parse.
    """
    try:
        text = str(fr).strip()
        if "/" in text:
            num_s, den_s = text.split("/", 1)
            num, den = float(num_s), float(den_s)
            if den == 0:
                return 0.0
            return num / den
        return float(text)
    except (ValueError, TypeError):
        return 0.0


def probe_video(path):
    r = subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json",
                        "-show_format", "-show_streams", str(path)],
                       capture_output=True, text=True)
    d = json.loads(r.stdout)
    for s in d.get("streams", []):
        if s["codec_type"] == "video":
            fr = s.get("r_frame_rate", "30/1")
            return {
                "duration": float(d["format"]["duration"]),
                "width": s["width"], "height": s["height"],
                "fps": parse_framerate(fr),
            }
    return None


def build_filtergraph(plan, num_graphics, W=None, H=None, fps=None):
    """Build the ffmpeg filtergraph for a scene plan.

    Returns (filtergraph, video_out_label, audio_out_label).
    """
    scenes = plan["scenes"]
    scene_durs = [sc["end_sec"] - sc["start_sec"] for sc in scenes]
    if W is None:
        W = plan["width"]
    if H is None:
        H = plan["height"]
    if fps is None:
        fps = plan["fps"]
    # ── build filtergraph ──
    lines = []
    seg_v, seg_a = [], []

    for i, sc in enumerate(scenes):
        mode = sc["mode"]
        g_idx = sc.get("graphic")
        start, end = sc["start_sec"], sc["end_sec"]
        dur = end - start

        pip_scale = sc.get("pip_scale", 0.25)
        pip_w = int(W * pip_scale)
        pip_h = int(pip_w * 9 / 16)
        pos = sc.get("pip_position", "bottom-right")
        pos_map = {
            "bottom-right": (W - pip_w - 30, H - pip_h - 30),
            "bottom-left": (30, H - pip_h - 30),
            "top-right": (W - pip_w - 30, 30),
            "top-left": (30, 30),
        }
        px, py = pos_map.get(pos, pos_map["bottom-right"])
        rad = min(pip_w, pip_h) // 8

        sv, sa = f"sv{i}", f"sa{i}"

        # trim presenter
        pv_filter = (
            f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS,"
            f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
            f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,"
            f"fps={fps},format=yuv420p"
        )

        # ── per-scene presenter effects ──
        effects = sc.get("effects", [])
        for eff in effects:
            etype = eff.get("type", "")
            if etype == "zoompan":
                z = eff.get("z", "1.2")
                x = eff.get("x", "iw/2-(iw/zoom/2)")
                y = eff.get("y", "ih/2-(ih/zoom/2)")
                d = eff.get("d", "1")
                pv_filter += f",zoompan=z='{z}':x='{x}':y='{y}':d={d}"
            elif etype == "chromakey":
                color = eff.get("color", "0x00FF00")
                similarity = eff.get("similarity", "0.1")
                blend = eff.get("blend", "0.08")
                pv_filter += f",chromakey={color}:{similarity}:{blend}"
            elif etype == "rotate":
                angle = eff.get("angle", "0.1")
                pv_filter += f",rotate={angle}*PI/180:out_h=ih:out_w=iw:fillcolor=black@0"
            elif etype == "hflip":
                pv_filter += ",hflip"
            elif etype == "vflip":
                pv_filter += ",vflip"

        # ── per-scene graphic effects ── (before mode composition)
        gv_filter = ""
        if g_idx is not None and g_idx < num_graphics:
            gv_filter = (
                f"[{g_idx+1}:v]trim=start=0:duration={dur},setpts=PTS-STARTPTS,"
                f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
                f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2"
            )
            gfx_effects = sc.get("graphic_effects", [])
            for eff in gfx_effects:
                etype = eff.get("type", "")
                if etype == "zoompan":
                    z = eff.get("z", "1.2")
                    gv_filter += f",zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1"
                elif etype == "rotate":
                    angle = eff.get("angle", "0.1")
                    gv_filter += f",rotate={angle}*PI/180:fillcolor=black@0"
            gv_filter += f"[gv{i}]"
            lines.append(gv_filter)
        elif g_idx is None:
            pass  # fullscreen scene: no graphic source needed

        lines.append(pv_filter + f"[pv{i}]")
        lines.append(f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[pa{i}]")

        # compose by mode
        if mode == "fullscreen":
            lines.append(f"[pv{i}]format=yuv420p[{sv}]")
            lines.append(f"[pa{i}]anull[{sa}]")

        elif mode == "bg_only":
            lines.append(f"[gv{i}]format=yuv420p[{sv}]")
            lines.append(f"[pa{i}]anull[{sa}]")

        elif mode == "corner":
            # rounded-rect PiP
            lines.append(
                f"[pv{i}]scale={pip_w}:{pip_h}:force_original_aspect_ratio=decrease,"
                f"pad={pip_w}:{pip_h}:(ow-iw)/2:(oh-ih)/2,format=rgba,"
                f"geq=a='if(lte(abs(X-W/2),W/2-{rad})*lte(abs(Y-H/2),H/2-{rad}),255,"
                f"if(lt(hypot(max(abs(X-W/2)-W/2+{rad},0),"
                f"max(abs(Y-H/2)-H/2+{rad},0)),{rad}),255,0))':"
                f"r='r(X,Y)':g='g(X,Y)':b='b(X,Y)'[pip{i}]"
            )
            lines.append(
                f"color=black@0.4:s={pip_w+4}x{pip_h+4}:r={fps}:d={dur}[sh{i}];"
                f"[sh{i}][pip{i}]overlay=2:2[pip{i}s]"
            )
            lines.append(
                f"[gv{i}][pip{i}s]overlay={px}:{py}:format=auto,format=yuv420p[{sv}]"
            )
            lines.append(f"[pa{i}]anull[{sa}]")

        seg_v.append(sv)
        seg_a.append(sa)

    # stitch with transitions — ALL FFmpeg xfade transitions supported natively
    # Pass transition name directly from JSON; it maps 1:1 to xfade filter.
    # Full list: fade, wipeleft, wiperight, wipeup, wipedown, slideleft, slideright,
    # slideup, slidedown, circlecrop, rectcrop, distance, fadeblack, fadewhite,
    # radial, smoothleft, smoothright, smoothup, smoothdown, circleopen, circleclose,
    # vertopen, vertclose, horzopen, horzclose, dissolve, pixelize, diagtl, diagtr,
    # diagbl, diagbr, hlslice, hrslice, vuslice, vdslice, hblur, fadegrays, wipetl,
    # wipetr, wipebl, wipebr, squeezeh, squeezev, zoomin, fadefast, fadeslow,
    # hlwind, hrwind, vuwind, vdwind, coverleft, coverright, coverup, coverdown,
    # revealleft, revealright, revealup, revealdown
    # For "none" we use a 0.01s fade (effectively instant snap)

    if len(seg_v) == 1:
        fg = ";\n".join(lines)
        vout, aout = seg_v[0], seg_a[0]
    else:
        cur_v, cur_a = seg_v[0], seg_a[0]
        running_dur = scene_durs[0]
        for i in range(1, len(seg_v)):
            td = scenes[i].get("transition_duration", 0.5)
            raw_transition = scenes[i].get("transition", "fade")

            # "none" = instant cut via minimal xfade
            if raw_transition == "none":
                xf, adj_td = "fade", 0.01
            else:
                xf, adj_td = raw_transition, td

            offset = running_dur - adj_td
            running_dur = running_dur + scene_durs[i] - adj_td

            nv = f"cv{i}"
            lines.append(f"[{cur_v}][{seg_v[i]}]xfade=transition={xf}:duration={adj_td}:offset={offset}[{nv}]")
            cur_v = nv

            na = f"ca{i}"
            lines.append(f"[{cur_a}][{seg_a[i]}]acrossfade=duration={adj_td}[{na}]")
            cur_a = na

        fg = ";\n".join(lines)
        vout, aout = cur_v, cur_a
    return fg, vout, aout


def pick_video_encoder():
    """Pick the first available H.264/MP4 video encoder on this host.

    Fedora's ffmpeg ships WITHOUT libx264; prefer hardware/native H.264
    encoders, fall back to mpeg4 (always present). Returns (codec, extra_args).
    """
    try:
        r = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"],
                           capture_output=True, text=True, timeout=30)
        encs = r.stdout
    except (OSError, subprocess.SubprocessError):
        return "mpeg4", []
    for codec, extra in (("libx264", ["-preset", "fast", "-crf", "18"]),
                         ("libopenh264", []),
                         ("h264_vaapi", []),
                         ("h264_nvenc", []),
                         ("h264_qsv", []),
                         ("mpeg4", [])):
        if re.search(rf"^\s*\S+\s+{codec}\b", encs, re.M):
            return codec, extra
    return "mpeg4", []


# 58 native xfade transitions (indices 0-57, verified via
# `ffmpeg -h filter=xfade`), plus the "none" alias (0.01s fade = cut).
TRANSITIONS = (
    "fade", "wipeleft", "wiperight", "wipeup", "wipedown",
    "slideleft", "slideright", "slideup", "slidedown",
    "circlecrop", "rectcrop", "distance", "fadeblack", "fadewhite",
    "radial", "smoothleft", "smoothright", "smoothup", "smoothdown",
    "circleopen", "circleclose", "vertopen", "vertclose",
    "horzopen", "horzclose", "dissolve", "pixelize",
    "diagtl", "diagtr", "diagbl", "diagbr",
    "hlslice", "hrslice", "vuslice", "vdslice",
    "hblur", "fadegrays",
    "wipetl", "wipetr", "wipebl", "wipebr",
    "squeezeh", "squeezev", "zoomin", "fadefast", "fadeslow",
    "hlwind", "hrwind", "vuwind", "vdwind",
    "coverleft", "coverright", "coverup", "coverdown",
    "revealleft", "revealright", "revealup", "revealdown",
)
MODES = ("fullscreen", "corner", "bg_only")
PIP_POSITIONS = ("bottom-right", "bottom-left", "top-right", "top-left")


def validate_plan(plan, num_graphics=0, graphic_durations=None):
    """Validate a scene plan. Returns a list of error strings (empty = valid).

    Checks: required keys, numeric timing, contiguous scenes starting at 0,
    graphic index bounds (+ optional duration >= scene duration),
    mode/transition/pip_position enums.
    """
    errors = []
    scenes = plan.get("scenes") if isinstance(plan, dict) else None
    if not isinstance(scenes, list) or not scenes:
        return ["plan.scenes must be a non-empty list"]
    for key in ("fps", "width", "height"):
        if key in plan and not isinstance(plan[key], (int, float)):
            errors.append(f"plan.{key} must be numeric, got {plan[key]!r}")
    expected_start = 0.0
    for i, sc in enumerate(scenes):
        where = f"scene[{i}]"
        for key in ("start_sec", "end_sec"):
            if key not in sc:
                errors.append(f"{where}: missing {key}")
            elif not isinstance(sc[key], (int, float)):
                errors.append(f"{where}: {key} must be numeric, got {sc[key]!r}")
        if isinstance(sc.get("start_sec"), (int, float)) and isinstance(sc.get("end_sec"), (int, float)):
            if sc["end_sec"] <= sc["start_sec"]:
                errors.append(f"{where}: end_sec ({sc['end_sec']}) must be > start_sec ({sc['start_sec']})")
            if abs(sc["start_sec"] - expected_start) > 1e-6:
                errors.append(f"{where}: scenes must be contiguous — start_sec {sc['start_sec']} != prev end {expected_start}")
            expected_start = sc["end_sec"]
        mode = sc.get("mode", "fullscreen")
        if mode not in MODES:
            errors.append(f"{where}: bad mode {mode!r}, must be one of {list(MODES)}")
        g = sc.get("graphic")
        if g is not None:
            if not isinstance(g, int):
                errors.append(f"{where}: graphic must be an int index or null, got {g!r}")
            elif g < 0 or g >= num_graphics:
                errors.append(f"{where}: graphic index {g} out of range (have {num_graphics} graphics)")
            elif graphic_durations is not None and g < len(graphic_durations):
                scene_dur = sc.get("end_sec", 0) - sc.get("start_sec", 0)
                if graphic_durations[g] < scene_dur:
                    errors.append(f"{where}: graphic #{g} is {graphic_durations[g]:.1f}s but scene needs {scene_dur:.1f}s")
        t = sc.get("transition", "fade")
        if t != "none" and t not in TRANSITIONS:
            errors.append(f"{where}: bad transition {t!r} (58 natives + 'none')")
        td = sc.get("transition_duration", 0.5)
        if not isinstance(td, (int, float)) or td < 0:
            errors.append(f"{where}: transition_duration must be a non-negative number, got {td!r}")
        if mode == "corner" and "pip_position" in sc and sc["pip_position"] not in PIP_POSITIONS:
            errors.append(f"{where}: bad pip_position {sc['pip_position']!r}, must be one of {list(PIP_POSITIONS)}")
        for key in ("pip_scale",):
            if key in sc and not isinstance(sc[key], (int, float)):
                errors.append(f"{where}: {key} must be numeric, got {sc[key]!r}")
    return errors


def normalize_presenter(src, dst, fps=30):
    """Re-encode VFR phone footage to CFR so xfade timestamps can't desync."""
    cmd = ["ffmpeg", "-y", "-i", str(src),
           "-vf", "setpts=PTS-STARTPTS", "-af", "asetpts=PTS-STARTPTS",
           "-r", str(fps), str(dst)]
    return subprocess.run(cmd, capture_output=True, text=True)


SAMPLE_SCRIPT = """# Demo Video

## Scene 1 — Hook (0s-12s)
Hi everyone, and welcome. Today we are talking about the pipeline.

## Scene 2 — Concept (12s-35s)
The key idea is simple: one render beats many stitches.
"""

SAMPLE_PLAN = {
    "fps": 30, "width": 1920, "height": 1080,
    "scenes": [
        {"mode": "fullscreen", "graphic": None,
         "start_sec": 0.0, "end_sec": 12.0,
         "transition": "fade", "transition_duration": 0.5},
        {"mode": "corner", "graphic": 0,
         "start_sec": 12.0, "end_sec": 35.0,
         "transition": "fade", "transition_duration": 0.5,
         "pip_position": "bottom-right", "pip_scale": 0.25},
    ],
}


def cmd_scaffold(args):
    """Create videos/<slug>/ layout with sample script.md + scene-plan.json."""
    root = Path(args.path)
    (root / "hf_project").mkdir(parents=True, exist_ok=True)
    (root / "graphics").mkdir(parents=True, exist_ok=True)
    (root / "out").mkdir(parents=True, exist_ok=True)
    script = root / "script.md"
    if not script.exists():
        script.write_text(SAMPLE_SCRIPT)
    plan = root / "scene-plan.json"
    if not plan.exists():
        plan.write_text(json.dumps(SAMPLE_PLAN, indent=2) + "\n")
    print(f"✓ Scaffolded {root} (script.md + scene-plan.json + hf_project/ + graphics/ + out/)")


def _hf_pip_css(sc, W, H):
    scale = sc.get("pip_scale", 0.25)
    pip_w = int(W * scale)
    pip_h = int(pip_w * 9 / 16)
    pos = sc.get("pip_position", "bottom-right")
    css_pos = {
        "bottom-right": f"right: 30px; bottom: 30px;",
        "bottom-left": f"left: 30px; bottom: 30px;",
        "top-right": f"right: 30px; top: 30px;",
        "top-left": f"left: 30px; top: 30px;",
    }[pos] if pos in PIP_POSITIONS else "right: 30px; bottom: 30px;"
    return (f"position: absolute; {css_pos} width: {pip_w}px; height: {pip_h}px;"
            f" object-fit: cover; border-radius: 16px;"
            f" border: 2px solid rgba(255,255,255,0.35); z-index: 5;")


def build_hf_project(plan, presenter_src, presenter_duration, out_dir,
                     vertical=False):
    """Generate a single HyperFrames project from a scene plan (Mode B).

    Uses the REAL composition contract: root #root with
    data-composition-id/start/duration/width/height, every visible slot a
    `.clip` with id + data-start/duration/track-index, presenter as a-roll
    video+audio, graphic overlays on track 1+, ONE paused GSAP timeline
    registered on window.__timelines["main"].

    Returns the index.html path. Raises ValueError on invalid plan.
    """
    scenes = plan.get("scenes", []) if isinstance(plan, dict) else []
    n_graphics = sum(1 for sc in scenes if sc.get("graphic") is not None)
    errors = validate_plan(plan, n_graphics)
    if errors:
        raise ValueError("invalid scene plan:\n" + "\n".join(f"  - {e}" for e in errors))
    W, H, fps = plan["width"], plan["height"], plan["fps"]
    total = scenes[-1]["end_sec"]
    if presenter_duration < total:
        raise ValueError(f"presenter is {presenter_duration:.1f}s but plan needs {total:.1f}s")

    clips = []
    timeline_steps = []
    for i, sc in enumerate(scenes):
        start, dur = sc["start_sec"], sc["end_sec"] - sc["start_sec"]
        title = sc.get("title", f"Scene {i + 1}")
        mode, g = sc.get("mode", "fullscreen"), sc.get("graphic")
        if mode == "corner":
            # presenter shrinks to PiP during this scene
            timeline_steps.append(
                f'tl.to("#a-roll", {{ width: "{int(W * sc.get("pip_scale", 0.25))}px",'
                f' height: "{int(W * sc.get("pip_scale", 0.25) * 9 / 16)}px",'
                f" borderRadius: '16px', duration: 0.5 }}, {start});")
            pip_css = _hf_pip_css(sc, W, H)
            clips.append(
                f'      <div id="pip-label-{i}" class="clip" data-start="{start}"'
                f' data-duration="{dur}" data-track-index="3"'
                f' style="{pip_css} color: #fff;'
                f' font-size: 28px; padding: 8px 0;">{title}</div>')
        else:
            timeline_steps.append(
                f'tl.to("#a-roll", {{ width: "100%", height: "100%",'
                f" borderRadius: '0px', duration: 0.5 }}, {start});")
        if g is not None:
            clips.append(
                f'      <div id="graphic-{i}" class="clip" data-start="{start}"'
                f' data-duration="{dur}" data-track-index="1"'
                f' style="position: absolute; inset: 0; display: flex;'
                f' flex-direction: column; justify-content: center;'
                f' align-items: center; background: #0f172a; color: #f8fafc;'
                f' font-size: 72px; font-weight: 700; z-index: 2;">'
                f'<div class="scene-title">{title}</div>'
                f'<div class="scene-hint" style="font-size: 32px; color: #94a3b8;'
                f' margin-top: 16px;">replace with charts / captions / lower-thirds</div>'
                f"</div>")
        if mode == "bg_only":
            timeline_steps.append(
                f'tl.set("#a-roll", {{ opacity: 0 }}, {start});'
                f'tl.set("#a-roll", {{ opacity: 1 }}, {start + dur});')

    clips_html = "\n".join(clips) if clips else '      <!-- presenter-only -->'
    tl_html = "\n      ".join(timeline_steps)
    html = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width={W}, height={H}" />
    <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
    <style>
      * {{ margin: 0; padding: 0; box-sizing: border-box; }}
      html, body {{ margin: 0; width: {W}px; height: {H}px; overflow: hidden; background: #000; }}
      body {{ font-family: "Inter", sans-serif; }}
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-start="0"
      data-duration="{total}" data-width="{W}" data-height="{H}" data-fps="{fps}">
      <video id="a-roll" class="clip" src="{presenter_src}" muted playsinline
        data-start="0" data-duration="{total}" data-track-index="0"
        style="position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover"></video>
      <audio id="a-roll-audio" src="{presenter_src}" data-start="0"
        data-duration="{total}" data-track-index="2" data-volume="1"></audio>
{clips_html}
    </div>
    <script>
      window.__timelines = window.__timelines || {{}};
      const tl = gsap.timeline({{ paused: true }});
      {tl_html}
      window.__timelines["main"] = tl;
    </script>
  </body>
</html>
"""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    index = out / "index.html"
    index.write_text(html)
    return str(index)


def cmd_build_hf(args):
    plan = json.loads(Path(args.scene_plan).read_text())
    if args.presenter_duration is not None:
        pdur = float(args.presenter_duration)
    else:
        info = probe_video(args.presenter)
        if not info:
            print(f"❌ Could not probe presenter: {args.presenter}")
            sys.exit(1)
        pdur = info["duration"]
    try:
        index = build_hf_project(plan, args.presenter, pdur, args.output,
                                 vertical=args.vertical)
    except ValueError as e:
        print(f"❌ {e}")
        sys.exit(1)
    print(f"✓ HyperFrames project → {index}")


RENDER_IMAGE = "localhost/hyperframes-render:latest"


def render_hf_cmd(project_dir, output_path, fps="30", quality="standard",
                  image=RENDER_IMAGE):
    """Build the one-shot podman render command (pure, testable).

    Mounts the composition at /project:ro and the output dir at /output,
    mirroring HyperFrames' own --docker arg builder.
    """
    proj = Path(project_dir).resolve()
    out = Path(output_path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    # :Z relabels are REQUIRED on SELinux-enforcing hosts (Bluefin) —
    # without them the container sees EACCES on the bind mounts.
    return ["podman", "run", "--rm",
            "-v", f"{proj}:/project:ro,Z",
            "-v", f"{out.parent}:/output:Z",
            image, "/project",
            "--output", f"/output/{out.name}",
            "--fps", str(fps), "--quality", quality, "--format", "mp4"]


def cmd_render_hf(args):
    if not Path(args.project).is_dir():
        print(f"❌ Project dir not found: {args.project}")
        sys.exit(1)
    cmd = render_hf_cmd(args.project, args.output, args.fps, args.quality, args.image)
    print(f"▶ Rendering {args.project} → {args.output} (image {args.image})")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("❌ Render failed:")
        print((r.stderr or r.stdout)[-2000:])
        sys.exit(1)
    print(f"✅ {args.output}")


def cmd_composite(args):
    plan_path = args.scene_plan
    with open(plan_path) as f:
        plan = json.load(f)

    scenes = plan["scenes"]
    W, H, fps = plan["width"], plan["height"], plan["fps"]

    pres = Path(args.presenter)
    if not pres.exists():
        print(f"❌ Presenter not found: {pres}")
        sys.exit(1)

    graphics = [Path(p) for p in (args.graphics or [])]
    for g in graphics:
        if not g.exists():
            print(f"❌ Graphic not found: {g}")
            sys.exit(1)

    pinfo = probe_video(pres)
    if not pinfo:
        print("❌ Could not probe presenter video")
        sys.exit(1)

    graphic_durations = []
    for g in graphics:
        gi = probe_video(g)
        graphic_durations.append(gi["duration"] if gi else 0.0)

    errors = validate_plan(plan, len(graphics), graphic_durations)
    if errors:
        print("❌ Invalid scene plan:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    total_dur = scenes[-1]["end_sec"]
    if pinfo["duration"] < total_dur:
        print(f"⚠ Presenter is {pinfo['duration']:.1f}s but plan needs {total_dur:.1f}s")

    print(f"\n ▶ {len(scenes)} scenes, {total_dur:.1f}s total")
    for i, sc in enumerate(scenes):
        g = f"graphic #{sc['graphic']}" if sc.get("graphic") is not None else "just you"
        dur = sc["end_sec"] - sc["start_sec"]
        print(f"  {i+1}. [{sc['mode']:12s}] {dur:5.1f}s  {g}")

    fg, vout, aout = build_filtergraph(plan, len(graphics), W=W, H=H, fps=fps)

    vcodec, vextra = pick_video_encoder()
    # ── run ──
    cmd = ["ffmpeg", "-y", "-i", str(pres)]
    for g in graphics:
        cmd.extend(["-i", str(g)])
    cmd += ["-filter_complex", fg,
            "-map", f"[{vout}]", "-map", f"[{aout}]",
            "-c:v", vcodec] + vextra + [
            "-c:a", "aac", "-b:a", "192k",
            "-pix_fmt", "yuv420p", "-r", str(fps),
            str(Path(args.output))]

    print(f"\n Rendering...")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("❌ FFmpeg failed:")
        print(r.stderr[-1500:])
        sys.exit(1)

    out = Path(args.output)
    if out.exists() and out.stat().st_size > 0:
        info = probe_video(out)
        if info:
            print(f"✅ {out.name} — {info['width']}x{info['height']}, {info['duration']:.1f}s, {info['fps']:.1f}fps")


# ═══════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════

def main():
    if len(sys.argv) > 1 and sys.argv[1] == "new":
        parser = argparse.ArgumentParser(prog="impromptu new")
        parser.add_argument("path", nargs="?", default="script.md")
        cmd_new(parser.parse_args(sys.argv[2:]))
        return

    if len(sys.argv) > 1 and sys.argv[1] == "scaffold":
        parser = argparse.ArgumentParser(prog="impromptu scaffold")
        parser.add_argument("path", help="Project dir, e.g. videos/my-video/")
        cmd_scaffold(parser.parse_args(sys.argv[2:]))
        return

    if len(sys.argv) > 1 and sys.argv[1] == "composite":
        parser = argparse.ArgumentParser(prog="impromptu composite")
        parser.add_argument("scene_plan", help="Scene plan JSON")
        parser.add_argument("--presenter", "-p", required=True, help="Your recording")
        parser.add_argument("--graphics", "-g", nargs="+", help="HyperFrames graphic MP4s")
        parser.add_argument("--graphics-track", help="Single full-length Mode B graphic MP4")
        parser.add_argument("--output", "-o", default="output.mp4", help="Output path")
        parser.add_argument("--normalize", action="store_true",
                            help="Re-encode VFR presenter to CFR first")
        cmd_composite(parser.parse_args(sys.argv[2:]))
        return

    if len(sys.argv) > 1 and sys.argv[1] == "build-hf":
        parser = argparse.ArgumentParser(prog="impromptu build-hf")
        parser.add_argument("scene_plan", help="Scene plan JSON")
        parser.add_argument("--presenter", "-p", required=True, help="Presenter video path (referenced by the composition)")
        parser.add_argument("--presenter-duration", type=float, default=None,
                            help="Presenter duration in seconds (else ffprobed)")
        parser.add_argument("--output", "-o", default="hf_project", help="HF project dir")
        parser.add_argument("--vertical", action="store_true", help="1080x1920 Shorts layout")
        cmd_build_hf(parser.parse_args(sys.argv[2:]))
        return

    if len(sys.argv) > 1 and sys.argv[1] == "render-hf":
        parser = argparse.ArgumentParser(prog="impromptu render-hf")
        parser.add_argument("project", help="HyperFrames project dir")
        parser.add_argument("--output", "-o", required=True, help="Output MP4")
        parser.add_argument("--fps", default="30", help="Frame rate")
        parser.add_argument("--quality", default="standard", choices=["draft", "standard", "high"])
        parser.add_argument("--image", default="localhost/hyperframes-render:latest",
                            help="One-shot render image tag")
        cmd_render_hf(parser.parse_args(sys.argv[2:]))
        return

    # default: teleprompter
    parser = argparse.ArgumentParser(
        prog="impromptu",
        description="Terminal teleprompter. Usage: impromptu script.md [options]",
        epilog="""
Examples:
  impromptu script.md                   # run teleprompter
  impromptu script.md --speed 2.5       # faster scroll
  impromptu new my-script.md            # scaffold sample
  impromptu composite plan.json -p me.mp4 -g g1.mp4 -o final.mp4  # compose video

Controls (when running):
  Space    Play/Pause
  ↑/↓      Move up/down
  ←/→      Jump 5 lines back/forward
  +/-      Adjust speed
  0        Jump to start
  q        Quit
""",
    )
    parser.add_argument("script", nargs="?", help="Markdown script")
    parser.add_argument("--speed", type=float, default=1.5, help="Lines per second")
    parser.add_argument("--voice", action="store_true", help="(deprecated)")

    args = parser.parse_args()
    if args.script:
        cmd_prompter(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()