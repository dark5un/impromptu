"""Pixel-truth regression tests for board alpha compositing.

Why these exist
---------------
The comb/picket defect Panos reported in the demo master was invisible to every
structural assertion in the suite: frame count, duration, resolution, CFR and
even SSIM-against-the-previous-render all passed while the picture was wrong.
The defect was an *alpha convention* mismatch, and the only way to catch it is
to compare **pixels** against an independently computed reference.

The bug, precisely: HyperFrames emits **straight** (non-premultiplied) alpha,
and MLT's compositing path consumes the colour plane as if it were **already
premultiplied**. A pixel authored ``rgba(255,255,255,0.10)`` — the bar track in
the demo board — therefore composited as full white instead of dark grey.

These tests are skipped when ffmpeg/mlt-melt are unavailable so CI without the
render stack stays green, but they run for real in the container.
"""
from __future__ import annotations

import json
import shutil
import struct
import subprocess
import zlib
from pathlib import Path

import pytest

from render.board import PREMULTIPLY_FILTER, premultiply_command

_FFMPEG = shutil.which("ffmpeg")
_FFPROBE = shutil.which("ffprobe")
_MELT = shutil.which("mlt-melt") or shutil.which("melt-7")

needs_render_stack = pytest.mark.skipif(
    not (_FFMPEG and _FFPROBE and _MELT),
    reason="requires ffmpeg, ffprobe and mlt-melt",
)

# Narrowed for the type checker; every use is behind needs_render_stack, and
# premultiply_command supplies its own "ffmpeg" argv[0] for the unit tests.
FFMPEG = _FFMPEG or "ffmpeg"
FFPROBE = _FFPROBE or "ffprobe"
MELT = _MELT or "mlt-melt"

# The exact alpha value that exposed the bug: rgba(255,255,255,0.10).
TRACK_RGBA = (255, 255, 255, 26)


# ── unit level: the command contract ───────────────────────────────────────────

def test_premultiply_filter_is_the_ffmpeg_premultiply_with_inplace():
    """MLT wants premultiplied colour; inplace=1 multiplies by the input's own alpha."""
    assert PREMULTIPLY_FILTER == "premultiply=inplace=1"


def test_premultiply_command_preserves_prores_4444_alpha(tmp_path):
    """The conversion must stay ProRes 4444 with a full-resolution alpha plane.

    Re-encoding to anything without an alpha plane, or to VP9's quarter-res
    yuva420p, would defeat the point of rendering boards as MOV in the first
    place.
    """
    argv = premultiply_command(tmp_path / "straight.mov", tmp_path / "premul.mov")
    assert argv[0] == "ffmpeg"
    assert "-vf" in argv and argv[argv.index("-vf") + 1] == PREMULTIPLY_FILTER
    assert argv[argv.index("-c:v") + 1] == "prores_ks"
    assert argv[argv.index("-profile:v") + 1] == "4444"
    assert argv[argv.index("-pix_fmt") + 1].startswith("yuva444p")
    # audio is irrelevant for an overlay board and must not be invented
    assert "-an" in argv
    assert str(tmp_path / "straight.mov") in argv
    assert argv[-1] == str(tmp_path / "premul.mov")


# ── helpers for the pixel tests ───────────────────────────────────────────────

def _write_straight_alpha_png(path: Path, rgba: tuple[int, int, int, int],
                              width: int = 64, height: int = 64) -> None:
    """Write a flat RGBA PNG with the stdlib, no image library required."""
    raw = b"".join(
        b"\x00" + bytes(rgba) * width for _ in range(height)
    )

    def chunk(tag: bytes, payload: bytes) -> bytes:
        body = tag + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(
            ">I", zlib.crc32(body) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def _probe_pixel(path: Path, size: int = 64) -> tuple[int, int, int]:
    """Return the centre RGB pixel of the first frame, using ffmpeg only.

    The whole frame is decoded and indexed in Python rather than cropped in the
    filter graph: ffmpeg's ``crop`` rejects its own parameters on this build
    ("Invalid too big or non positive size for width '0'"), and a 64x64 frame is
    12KB, so there is nothing to gain from filtering.
    """
    raw = subprocess.run(
        [FFMPEG, "-v", "error", "-i", str(path),
         "-vf", "format=rgb24", "-vframes", "1", "-f", "rawvideo", "-"],
        check=True, capture_output=True).stdout
    assert len(raw) == size * size * 3, (
        f"expected a {size}x{size} rgb24 frame, got {len(raw)} bytes")
    offset = ((size // 2) * size + (size // 2)) * 3
    return raw[offset], raw[offset + 1], raw[offset + 2]


def _make_board_mov(png: Path, mov: Path, frames: int = 4) -> None:
    """Encode a still into a short straight-alpha ProRes 4444 board."""
    subprocess.run(
        [FFMPEG, "-v", "error", "-y", "-loop", "1", "-i", str(png),
         "-frames:v", str(frames), "-r", "30",
         "-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le",
         "-an", str(mov)],
        check=True)


def _composite_over_black(board: Path, project: Path, output: Path,
                          frames: int = 4) -> None:
    """Composite *board* over black through the same affine path as a render."""
    project.write_text(f"""<?xml version='1.0' encoding='utf-8'?>
<mlt LC_NUMERIC="C" profile="test">
  <profile description="test" width="64" height="64" progressive="1"
    sample_aspect_num="1" sample_aspect_den="1" display_aspect_num="1"
    display_aspect_den="1" frame_rate_num="30" frame_rate_den="1" colorspace="709"/>
  <producer id="bg">
    <property name="resource">color:black</property>
    <property name="length">{frames * 4}</property>
  </producer>
  <producer id="board">
    <property name="resource">{board}</property>
  </producer>
  <playlist id="pbg"><entry producer="bg" in="0" out="{frames - 1}"/></playlist>
  <playlist id="pboard"><entry producer="board" in="0" out="{frames - 1}"/></playlist>
  <tractor id="main" global_feed="1">
    <track producer="pbg"/>
    <track producer="pboard"/>
    <transition id="composite">
      <property name="mlt_service">affine</property>
      <property name="a_track">0</property>
      <property name="b_track">1</property>
      <property name="rect">0%/0%:100%x100%:100%</property>
      <property name="fill">1</property>
      <property name="distort">0</property>
    </transition>
  </tractor>
</mlt>
""")
    subprocess.run(
        [MELT, str(project), "-consumer", f"avformat:{output}",
         "vcodec=ffv1", "real_time=-1", "threads=1", "an=1"],
        check=True, capture_output=True)


# ── pixel level: the actual defect ────────────────────────────────────────────

@needs_render_stack
def test_semi_transparent_board_pixel_composites_to_its_straight_alpha_value(tmp_path):
    """A 10%-opaque white board pixel over black must land near 26, not 255.

    This is the exact defect from the demo master: the bar track authored as
    ``rgba(255,255,255,.10)`` rendered pure white. Straight alpha over black is
    ``colour * alpha`` = 255 * 0.10 ≈ 26.
    """
    png = tmp_path / "flat.png"
    straight = tmp_path / "straight.mov"
    premul = tmp_path / "premul.mov"
    _write_straight_alpha_png(png, TRACK_RGBA)
    _make_board_mov(png, straight)
    subprocess.run(premultiply_command(straight, premul), check=True,
                   capture_output=True)

    rendered = tmp_path / "out.mkv"
    _composite_over_black(premul, tmp_path / "p.mlt", rendered)

    r, g, b = _probe_pixel(rendered)
    expected = TRACK_RGBA[0] * TRACK_RGBA[3] / 255.0  # ≈ 26
    for channel in (r, g, b):
        assert abs(channel - expected) <= 6, (
            f"semi-transparent board pixel composited to {(r, g, b)}, expected "
            f"≈{expected:.0f} per channel. A value near 255 means the alpha "
            "convention regressed: MLT consumed straight alpha as premultiplied."
        )


@needs_render_stack
def test_straight_alpha_board_is_wrong_which_is_why_we_premultiply(tmp_path):
    """Guard the *reason* for the conversion, so nobody removes it as redundant.

    Feeding MLT the straight-alpha board directly reproduces the original bug.
    If this ever stops being true — MLT changed its convention — the premultiply
    step becomes a double-multiply and must be revisited, so failing here is the
    correct alarm.
    """
    png = tmp_path / "flat.png"
    straight = tmp_path / "straight.mov"
    _write_straight_alpha_png(png, TRACK_RGBA)
    _make_board_mov(png, straight)

    rendered = tmp_path / "out.mkv"
    _composite_over_black(straight, tmp_path / "p.mlt", rendered)

    r, _, _ = _probe_pixel(rendered)
    assert r > 200, (
        f"straight-alpha board composited to {r}, not the ~255 this bug "
        "produces. MLT's alpha convention may have changed; re-verify whether "
        "premultiply_command is still required."
    )


@needs_render_stack
def test_opaque_board_pixels_are_unchanged_by_premultiplying(tmp_path):
    """Premultiplying must be a no-op where alpha is 1.0.

    Fully opaque graphics — most of any board — must survive byte-for-byte, or
    the fix would trade one visual regression for another.
    """
    png = tmp_path / "opaque.png"
    straight = tmp_path / "straight.mov"
    premul = tmp_path / "premul.mov"
    _write_straight_alpha_png(png, (90, 247, 142, 255))  # brand green, opaque
    _make_board_mov(png, straight)
    subprocess.run(premultiply_command(straight, premul), check=True,
                   capture_output=True)

    rendered = tmp_path / "out.mkv"
    _composite_over_black(premul, tmp_path / "p.mlt", rendered)

    r, g, b = _probe_pixel(rendered)
    for actual, want in zip((r, g, b), (90, 247, 142)):
        assert abs(actual - want) <= 6, (
            f"opaque board pixel composited to {(r, g, b)}, expected "
            "(90, 247, 142); premultiplying must not alter opaque colour."
        )


@needs_render_stack
def test_premultiplied_board_keeps_frame_count_and_alpha_plane(tmp_path):
    """The conversion must not resample, retime, or drop the alpha plane."""
    png = tmp_path / "flat.png"
    straight = tmp_path / "straight.mov"
    premul = tmp_path / "premul.mov"
    _write_straight_alpha_png(png, TRACK_RGBA)
    _make_board_mov(png, straight, frames=7)
    subprocess.run(premultiply_command(straight, premul), check=True,
                   capture_output=True)

    def probe(path: Path) -> dict:
        out = subprocess.run(
            [FFPROBE, "-v", "error", "-select_streams", "v:0",
             "-count_frames", "-show_entries",
             "stream=nb_read_frames,pix_fmt,width,height,r_frame_rate",
             "-of", "json", str(path)],
            check=True, capture_output=True, text=True).stdout
        return json.loads(out)["streams"][0]

    before, after = probe(straight), probe(premul)
    assert after["nb_read_frames"] == before["nb_read_frames"] == "7"
    assert after["width"] == before["width"]
    assert after["height"] == before["height"]
    assert after["r_frame_rate"] == before["r_frame_rate"]
    assert after["pix_fmt"].startswith("yuva444p"), (
        f"alpha plane lost: pix_fmt is {after['pix_fmt']}")
