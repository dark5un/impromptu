"""The MCP tool surface: intent-shaped tools, not auto-derived REST routes.

The plan calls for ~12 hand-written tools named after what the user wants
(`doc.patch`, `reconcile.run`, `render.start`) rather than a mechanical mirror
of the HTTP API.  These tests pin the roster and the safety boundaries: MCP is
how an agent drives the studio, so a tool that silently uploads or escapes the
productions root would be the worst possible bug here.
"""
import asyncio
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

pytest.importorskip("fastmcp", reason="web extra not installed")

from fastmcp.exceptions import ToolError

from api.mcp import get_mcp

EXPECTED_TOOLS = {
    "list_productions",
    "create_production",
    "validate_document",
    "read_document",
    "patch_document",
    "reconcile_run",
    "direct_run",
    "boards_build",
    "render_start",
    "package_run",
    "drift_report",
    "scene_layout",
}


def tools():
    return {tool.name: tool for tool in asyncio.run(get_mcp()._list_tools())}


def call(name, **arguments):
    """Invoke one tool the way a client would and return its payload.

    FastMCP 4 wraps a non-content return value as ``{"result": ...}`` in
    ``structured_content``; unwrap it so the assertions read naturally.
    """
    result = asyncio.run(get_mcp().call_tool(name, arguments))
    content = getattr(result, "structured_content", None)
    if content is None:
        return result
    return content.get("result", content)


def production(tmp_path: Path) -> Path:
    doc = {
        "schema": 1, "title": "Demo",
        "target": {"orientation": "landscape", "resolution": [1920, 1080], "fps": 30},
        "media": {}, "presenter": {"source": "takes/take.mp4"},
        "scenes": [
            {"id": "one", "say": "Hello world", "planned_sec": 2.0, "measured_sec": None,
             "segments": None, "presenter": None, "overlay": None, "transition": None},
            {"id": "two", "say": "Goodbye now", "planned_sec": 3.0, "measured_sec": None,
             "segments": None, "presenter": None, "overlay": None, "transition": None},
        ],
    }
    directory = tmp_path / "chapter-1"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "production.yaml").write_text(yaml.safe_dump(doc, sort_keys=False))
    return directory


# ── the roster ───────────────────────────────────────────────────────────────

def test_every_planned_intent_tool_is_registered():
    missing = EXPECTED_TOOLS - set(tools())
    assert not missing, f"MCP is missing intent tools: {sorted(missing)}"


def test_tools_are_intent_named_not_http_verbs():
    for name in tools():
        assert not name.startswith(("get_", "post_", "put_", "delete_")), name


def test_every_tool_documents_itself():
    """An agent picks tools by description, so an undocumented tool is unusable."""
    for name, tool in tools().items():
        assert tool.description, f"{name} has no description"


# ── reading and editing the document ────────────────────────────────────────

def test_read_document_returns_the_parsed_document(tmp_path):
    directory = production(tmp_path)
    result = call("read_document", path=str(directory))
    assert result["title"] == "Demo"
    assert len(result["scenes"]) == 2


def test_patch_document_edits_one_field(tmp_path):
    directory = production(tmp_path)
    call("patch_document", path=str(directory), changes={"title": "Renamed"})
    assert yaml.safe_load((directory / "production.yaml").read_text())["title"] == "Renamed"


def test_patch_document_rejects_an_edit_that_invalidates_the_document(tmp_path):
    directory = production(tmp_path)
    with pytest.raises(ToolError):
        call("patch_document", path=str(directory), changes={"schema": 99})
    # the file on disk must be untouched
    assert yaml.safe_load((directory / "production.yaml").read_text())["schema"] == 1


def test_validate_document_reports_errors_without_raising(tmp_path):
    directory = production(tmp_path)
    (directory / "production.yaml").write_text("schema: 1\n")
    result = call("validate_document", path=str(directory))
    assert result["valid"] is False
    assert result["errors"]


# ── the editorial pipeline ───────────────────────────────────────────────────

def test_reconcile_run_writes_measured_durations_and_returns_drift(tmp_path):
    directory = production(tmp_path)
    transcript = tmp_path / "t.json"
    transcript.write_text(
        '{"segments":[{"start":0,"end":1.5,"text":"Hello world"},'
        '{"start":1.5,"end":4.0,"text":"Goodbye now"}]}'
    )
    result = call("reconcile_run", path=str(directory), transcript_json=str(transcript))
    assert result["drift"][0]["measured_sec"] == 1.5
    saved = yaml.safe_load((directory / "production.yaml").read_text())
    assert saved["scenes"][0]["measured_sec"] == 1.5


def test_direct_run_fills_null_treatments(tmp_path):
    directory = production(tmp_path)
    result = call("direct_run", path=str(directory))
    assert [scene["presenter"] for scene in result["scenes"]] == ["fullscreen", "fullscreen"]


def test_direct_run_preserves_a_human_decision_unless_forced(tmp_path):
    directory = production(tmp_path)
    call("patch_document", path=str(directory),
         changes={"scenes": [
             {"id": "one", "say": "Hello world", "planned_sec": 2.0, "measured_sec": None,
              "segments": None, "presenter": "corner", "overlay": None,
              "transition": {"type": "wipeleft", "dur": 0.8}},
             {"id": "two", "say": "Goodbye now", "planned_sec": 3.0, "measured_sec": None,
              "segments": None, "presenter": None, "overlay": None, "transition": None},
         ]})
    kept = call("direct_run", path=str(directory))
    assert kept["scenes"][0]["presenter"] == "corner"
    forced = call("direct_run", path=str(directory), force=True)
    assert forced["scenes"][0]["presenter"] == "fullscreen"


def test_scene_layout_exposes_programme_timing(tmp_path):
    directory = production(tmp_path)
    call("direct_run", path=str(directory))
    layout = call("scene_layout", path=str(directory))
    assert [item["id"] for item in layout] == ["one", "two"]
    assert layout[0]["program_start"] == 0.0


def test_drift_report_is_readable_after_reconcile(tmp_path):
    directory = production(tmp_path)
    transcript = tmp_path / "t.json"
    transcript.write_text('{"segments":[{"start":0,"end":1.5,"text":"Hello world"}]}')
    call("reconcile_run", path=str(directory), transcript_json=str(transcript))
    report = call("drift_report", path=str(directory))
    assert any(row["scene"] == "one" for row in report)


# ── the boundaries that matter ───────────────────────────────────────────────

def test_render_start_refuses_a_document_with_unbuilt_boards(tmp_path):
    directory = production(tmp_path)
    call("patch_document", path=str(directory), changes={
        "media": {"chart": {"type": "board", "src": "boards/chart.html"}},
    })
    call("patch_document", path=str(directory), changes={"scenes": [
        {"id": "one", "say": "Hello world", "planned_sec": 2.0, "measured_sec": 2.0,
         "segments": None, "presenter": "corner", "overlay": "chart",
         "transition": {"type": "cut", "dur": 0.0}},
        {"id": "two", "say": "Goodbye now", "planned_sec": 3.0, "measured_sec": 3.0,
         "segments": None, "presenter": "fullscreen", "overlay": None,
         "transition": {"type": "cut", "dur": 0.0}},
    ]})
    with pytest.raises(ToolError):
        call("render_start", path=str(directory))


def test_package_run_refuses_when_the_master_is_missing(tmp_path):
    directory = production(tmp_path)
    with pytest.raises(ToolError):
        call("package_run", path=str(directory))


def test_no_tool_uploads_anything():
    """Upload is always manual; an MCP tool must never publish."""
    for name, tool in tools().items():
        blob = f"{name} {tool.description or ''}".lower()
        assert "upload to" not in blob
        assert "publish" not in blob
