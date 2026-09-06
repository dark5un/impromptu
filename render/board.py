"""HyperFrames board contracts, starter templates, and cached builds."""
from __future__ import annotations

import hashlib
import html as html_lib
import os
import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any


class BoardError(ValueError):
    """Base error for invalid or failed board builds."""


class BoardDurationError(BoardError):
    """A board duration does not match its reconciled scene duration."""


_ROOT_RE = re.compile(r"<[^>]*\bid\s*=\s*([\"'])root\1[^>]*>", re.IGNORECASE)
_ATTR_RE = re.compile(r"\b([\w-]+)\s*=\s*([\"'])(.*?)\2", re.DOTALL)
_ORIENTATIONS = {"landscape": (1920, 1080), "vertical": (1080, 1920)}
STARTER_TEMPLATES = ("title_card", "bar_chart", "lower_third", "code_reveal")


def _html_bytes(source: str | bytes | Path) -> bytes:
    if isinstance(source, Path):
        return source.read_bytes()
    return source.encode() if isinstance(source, str) else source


def extract_duration(html: str | bytes | Path) -> float:
    """Extract the numeric ``data-duration`` from the root composition element."""
    text = _html_bytes(html).decode()
    root = _ROOT_RE.search(text)
    if root is None:
        raise BoardError("board has no root element with id=\"root\"")
    attrs = {name.lower(): value for name, _, value in _ATTR_RE.findall(root.group(0))}
    raw = attrs.get("data-duration")
    if raw is None:
        raise BoardError("board root has no data-duration")
    try:
        duration = float(raw)
    except ValueError as exc:
        raise BoardError(f"invalid board data-duration {raw!r}") from exc
    if duration <= 0:
        raise BoardError("board data-duration must be positive")
    return duration


def declared_duration(path: str | Path) -> float:
    """Compatibility wrapper reading a board file."""
    return extract_duration(Path(path).read_bytes())


def validate_duration(board_duration: float, measured_sec: float, *, fps: float) -> bool:
    """Require board and scene durations to agree within one frame."""
    tolerance = 1.0 / float(fps)
    if abs(float(board_duration) - float(measured_sec)) > tolerance + 1e-9:
        raise BoardDurationError(
            f"board duration mismatch: declared {board_duration:.6f}s, "
            f"scene measured_sec {measured_sec:.6f}s (tolerance {tolerance:.6f}s)"
        )
    return True


def board_cache_key(html: str | bytes, measured_duration: float) -> str:
    """Return a content address for exact HTML bytes and measured duration."""
    payload = _html_bytes(html) + b"\0" + str(float(measured_duration)).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def board_cache_path(board: str | Path, cache_dir: str | Path, duration: float) -> Path:
    """Return the content-addressed movie path for a board file."""
    source = Path(board)
    return Path(cache_dir) / f"{source.stem}-{board_cache_key(source.read_bytes(), duration)}.mov"


def hyperframes_command(board: str | Path, output: str | Path, fps: float = 30) -> list[str]:
    """Build the subprocess argv for a transparent ProRes MOV board render."""
    source = Path(board)
    return [
        "hyperframes", "render", str(source.parent),
        "--composition", source.name,
        "--output", str(output), "--format", "mov", "--fps", str(fps),
    ]


def vendor_gsap(project: str | Path, *, source: str | Path | None = None) -> Path:
    """Stage GSAP at ``<project>/vendor/gsap.min.js`` for an offline render.

    Boards reference ``/vendor/gsap.min.js`` because the stock HyperFrames
    template's ``cdn.jsdelivr.net`` URL is unreachable in the container: the
    render reaches the capture stage, launches Chrome, then aborts with
    ``sub_timeline_script_failure``.  The container bakes GSAP in and exports
    ``IMPROMPTU_VENDOR``; *source* overrides that for tests and host runs.
    """
    if source is None:
        base = os.environ.get("IMPROMPTU_VENDOR", "/opt/impromptu/vendor")
        source = Path(base) / "gsap.min.js"
    origin = Path(source)
    if not origin.is_file():
        raise BoardError(
            f"vendored gsap.min.js not found at {origin}. Boards load "
            "/vendor/gsap.min.js locally because the CDN is unreachable offline; "
            "set IMPROMPTU_VENDOR to a directory containing gsap.min.js."
        )
    destination = Path(project) / "vendor" / "gsap.min.js"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(origin.read_bytes())
    return destination


def render_board(
    board: str | Path,
    cache_dir: str | Path,
    *,
    measured_sec: float,
    fps: float = 30,
    runner: Callable[..., Any] = subprocess.run,
    command: list[str] | None = None,
    vendor: bool = True,
) -> Path:
    """Validate and render one board, returning its cached MOV artifact."""
    source = Path(board)
    validate_duration(declared_duration(source), measured_sec, fps=fps)
    destination = board_cache_path(source, cache_dir, measured_sec)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.stat().st_size > 0:
        return destination
    # Boards reference /vendor/gsap.min.js; stage it beside the composition or
    # the render aborts in Chrome with sub_timeline_script_failure.
    if vendor:
        vendor_gsap(source.parent)
    argv = command or hyperframes_command(source, destination, fps=fps)
    completed = runner(argv, check=True)
    if completed is not None and getattr(completed, "returncode", 0) not in (0, None):
        raise BoardError(f"board render failed with exit code {completed.returncode}")
    if not destination.exists():
        raise BoardError(f"board renderer did not create {destination}")
    return destination


def build_boards(
    document: dict[str, Any],
    *,
    root: str | Path = ".",
    cache_dir: str | Path | None = None,
    runner: Callable[..., Any] = subprocess.run,
    vendor: bool = True,
) -> dict[str, Path]:
    """Build each named board referenced by a scene overlay exactly once."""
    root_path = Path(root)
    cache = Path(cache_dir) if cache_dir is not None else root_path / ".cache" / "boards"
    result: dict[str, Path] = {}
    for scene in document.get("scenes", []):
        name = scene.get("overlay")
        if not name or name in result:
            continue
        media = document.get("media", {}).get(name)
        if not media or media.get("type") != "board":
            continue
        measured = scene.get("measured_sec")
        if measured is None:
            raise BoardDurationError(f"board {name!r} requires scene measured_sec")
        result[name] = render_board(
            root_path / media["src"], cache, measured_sec=float(measured),
            fps=float(document["target"]["fps"]), runner=runner, vendor=vendor,
        )
    return result


def render_document_boards(document: dict[str, Any], root: str | Path, cache_dir: str | Path, *, command_factory=None) -> dict[str, Path]:
    """Backward-compatible name for :func:`build_boards`."""
    if command_factory is not None:
        raise ValueError("command_factory is no longer supported; pass runner")
    return build_boards(document, root=root, cache_dir=cache_dir)


def render_template(name: str, *, duration: float, orientation: str = "landscape") -> str:
    """Return a transparent starter board with the HyperFrames GSAP contract."""
    if orientation not in _ORIENTATIONS:
        raise ValueError("orientation must be landscape or vertical")
    if name not in STARTER_TEMPLATES:
        raise ValueError(f"unknown starter template {name!r}")
    width, height = _ORIENTATIONS[orientation]
    safe_name = html_lib.escape(name)
    return f'''<!doctype html>
<html><head><meta charset="utf-8"><script src="/vendor/gsap.min.js"></script></head>
<body><div id="root" data-composition-id="main" data-start="0" data-duration="{duration}" data-width="{width}" data-height="{height}">
  <div class="clip" data-start="0" data-duration="{duration}" data-track-index="1" data-board="{safe_name}"></div>
</div><script>
window.__timelines = window.__timelines || {{}};
window.__timelines["main"] = gsap.timeline({{ paused: true }});
</script></body></html>'''


def starter_template(name: str, *, duration: float, orientation: str = "landscape") -> str:
    """Alias for :func:`render_template` used by callers authoring starter boards."""
    return render_template(name, duration=duration, orientation=orientation)


class _StarterTemplates(dict[str, Callable[..., str]]):
    """Named starter factories retaining the legacy callable interface."""

    def __init__(self) -> None:
        super().__init__({
            name: (lambda *, duration, orientation="landscape", _name=name:
                   render_template(_name, duration=duration, orientation=orientation))
            for name in STARTER_TEMPLATES
        })

    def __call__(self) -> _StarterTemplates:
        """Return this container for callers using the legacy function form."""
        return self


starter_templates = _StarterTemplates()


__all__ = [
    "STARTER_TEMPLATES",
    "BoardDurationError",
    "BoardError",
    "board_cache_key",
    "board_cache_path",
    "build_boards",
    "declared_duration",
    "extract_duration",
    "hyperframes_command",
    "render_board",
    "render_document_boards",
    "render_template",
    "starter_template",
    "starter_templates",
    "validate_duration",
    "vendor_gsap",
]
