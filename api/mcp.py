"""Optional FastMCP tools for intent-shaped studio actions.

The tools are hand-written and named for what the user wants — patch the
document, run reconcile, start a render — rather than auto-derived from the
REST routes.  An agent reads these names and descriptions to decide what to do,
so each one states its effect and its boundary.

Two rules hold across every tool:

* ``production.yaml`` is the only decision artifact any of them writes.
* Nothing publishes.  ``package_run`` produces an upload checklist; uploading
  stays manual, by design.

FastMCP is deliberately not emulated: callers get an actionable dependency
error when the optional web stack is not installed.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    from fastmcp import FastMCP
except ImportError as exc:  # pragma: no cover - environment dependent
    FastMCP = None
    FASTMCP_IMPORT_ERROR: ImportError | None = exc
else:
    FASTMCP_IMPORT_ERROR = None


def _require_fastmcp():
    if FASTMCP_IMPORT_ERROR is not None:
        raise RuntimeError(
            "MCP support requires the optional fastmcp dependency (FastMCP). Install with "
            "`uv sync --extra web` (or `uv pip install -e '.[web]'`)."
        ) from FASTMCP_IMPORT_ERROR
    return FastMCP


def _production_path(directory: str | Path) -> Path:
    """Accept either a production directory or the document itself."""
    path = Path(directory)
    return path if path.is_file() else path / "production.yaml"


def get_mcp():
    """Return a configured FastMCP server; never silently substitute a fake."""
    mcp_type = _require_fastmcp()
    mcp = mcp_type("impromptu studio")

    # ── discovery ────────────────────────────────────────────────────────────

    @mcp.tool()
    def list_productions(root: str = "videos") -> list[str]:
        """List production directory names under *root*."""
        return sorted(p.name for p in Path(root).iterdir() if p.is_dir()) if Path(root).is_dir() else []

    @mcp.tool()
    def create_production(name: str, root: str = "videos") -> str:
        """Create a production directory with media, takes, and out folders."""
        from api.http import create_production as _create
        return str(_create(root, name))

    # ── the document ─────────────────────────────────────────────────────────

    @mcp.tool()
    def validate_document(path: str) -> dict[str, Any]:
        """Validate one production.yaml and return its errors without raising."""
        from api.http import validate_production_file
        errors = validate_production_file(_production_path(path))
        return {"valid": not errors, "errors": errors}

    @mcp.tool()
    def read_document(path: str) -> dict[str, Any]:
        """Read and return the validated production document."""
        from core.document import load_document
        return load_document(_production_path(path))

    @mcp.tool()
    def patch_document(path: str, changes: dict[str, Any]) -> dict[str, Any]:
        """Patch document fields by dotted path, rejecting invalid results.

        The file is left untouched if the patch would produce a document that
        fails validation, so a bad edit cannot corrupt the only decision file.
        """
        from core.document import patch_document as _patch
        return _patch(_production_path(path), changes)

    # ── the editorial pipeline ───────────────────────────────────────────────

    @mcp.tool()
    def reconcile_run(path: str, transcript_json: str | None = None,
                      take: str | None = None,
                      whisper_command: list[str] | None = None) -> dict[str, Any]:
        """Measure what was actually said and write it into the document.

        Sets measured_sec and scene-relative segments per scene from a
        transcript fixture or a JSON-producing whisper command, and returns the
        planned-vs-measured drift. Run this before authoring boards.
        """
        from core.reconcile import reconcile_document
        result = reconcile_document(_production_path(path), transcript_json=transcript_json,
                                    take=take, whisper_command=whisper_command)
        return {"drift": result["drift"], "scenes": result["scenes"]}

    @mcp.tool()
    def direct_run(path: str, force: bool = False) -> dict[str, Any]:
        """Decide presenter treatment and transitions for undecided scenes.

        Only fields left null are filled, so your manual edits survive. Pass
        force=true to re-decide every scene and discard those edits.
        """
        from core.direct import direct_production
        return direct_production(_production_path(path), force=force)

    @mcp.tool()
    def scene_layout(path: str) -> list[dict[str, Any]]:
        """Show each scene's programme position, take offset, and treatment.

        This is the timing view: where every scene lands on the output
        timeline once transition overlaps are applied.
        """
        from core.direct import direct_document
        from core.document import load_document
        from render.mlt_xml import scene_layout as _layout
        document = direct_document(load_document(_production_path(path)))
        return _layout(document)

    @mcp.tool()
    def drift_report(path: str) -> list[dict[str, Any]]:
        """Report planned vs measured duration per scene, to see where you ran long."""
        from core.document import load_document
        document = load_document(_production_path(path))
        rows = []
        for scene in document["scenes"]:
            planned = float(scene["planned_sec"])
            measured = scene.get("measured_sec")
            rows.append({
                "scene": scene["id"], "planned_sec": planned,
                "measured_sec": measured,
                "delta_sec": None if measured is None else round(float(measured) - planned, 6),
            })
        return rows

    # ── build and deliver ────────────────────────────────────────────────────

    @mcp.tool()
    def boards_build(path: str) -> dict[str, str]:
        """Render each board to cached ProRes 4444 alpha, guarding its duration.

        Fails if a board's data-duration disagrees with its scene's
        measured_sec by more than one frame, so run reconcile first.
        """
        from core.document import load_document
        from render.board import build_boards
        source = _production_path(path)
        document = load_document(source)
        built = build_boards(document, root=source.parent)
        return {name: str(artifact) for name, artifact in built.items()}

    @mcp.tool()
    def render_start(path: str, threads: int = 1) -> str:
        """Composite the document to out/master.mp4 via MLT and return its path.

        Boards must already be built: this step composites, it does not launch
        a browser, and an unbuilt board is a named error rather than a silently
        broken picture.
        """
        from render.pipeline import render_production
        return str(render_production(_production_path(path).parent, threads=threads))

    @mcp.tool()
    def package_run(path: str) -> dict[str, str]:
        """Produce the deliverables: loudness-normalised master, thumbnail,
        chapters, description, and an upload checklist.

        impromptu NEVER uploads. The checklist is the handoff to you.
        """
        from render.pipeline import package_production
        result = package_production(_production_path(path).parent)
        return {name: str(artifact) for name, artifact in result.items()}

    return mcp


def tool_manifest() -> str:
    """Return the registered tool names as JSON, for docs and smoke checks."""
    import asyncio
    names = sorted(tool.name for tool in asyncio.run(get_mcp()._list_tools()))
    return json.dumps(names, indent=2)


__all__ = ["FASTMCP_IMPORT_ERROR", "get_mcp", "tool_manifest"]
