"""Optional FastMCP tools for intent-shaped studio actions.

FastMCP is deliberately not emulated: callers get an actionable dependency
error when the optional web stack is not installed.
"""
from __future__ import annotations

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


def get_mcp():
    """Return a configured FastMCP server; never silently substitute a fake."""
    mcp_type = _require_fastmcp()
    mcp = mcp_type("impromptu studio")

    @mcp.tool()
    def list_productions(root: str = "videos") -> list[str]:
        """List production directory names."""
        return sorted(p.name for p in Path(root).iterdir() if p.is_dir()) if Path(root).is_dir() else []

    @mcp.tool()
    def validate_document(path: str) -> dict[str, Any]:
        """Validate one production.yaml and return errors."""
        from api.http import validate_production_file
        errors = validate_production_file(path)
        return {"valid": not errors, "errors": errors}

    @mcp.tool()
    def create_production(name: str, root: str = "videos") -> str:
        """Create a production directory with media, takes, and out folders."""
        from api.http import create_production
        return str(create_production(root, name))

    return mcp


__all__ = ["FASTMCP_IMPORT_ERROR", "get_mcp"]
