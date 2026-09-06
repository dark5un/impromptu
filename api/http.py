"""HTTP surface for the local impromptu studio.

The pure filesystem helpers intentionally do not require FastAPI.  Install the
``web`` extra to create the ASGI application: ``uv sync --extra web``.
"""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Any

from core.document import validate_document

try:  # Optional so document helpers remain usable in the base CLI install.
    from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles
except ImportError as exc:  # pragma: no cover - depends on environment
    FastAPI = File = HTTPException = UploadFile = WebSocket = None
    FileResponse = StaticFiles = None
    FASTAPI_IMPORT_ERROR: ImportError | None = exc
else:
    FASTAPI_IMPORT_ERROR = None

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def content_hash(payload: bytes) -> str:
    """Return the SHA-256 hex digest used for content-addressed uploads."""
    return hashlib.sha256(payload).hexdigest()


def safe_production_name(name: str) -> str:
    """Validate one directory name and reject traversal or separators."""
    if not isinstance(name, str) or not _NAME.fullmatch(name) or name in {".", ".."}:
        raise ValueError(f"invalid production name: {name!r}")
    return name


def list_productions(root: str | Path) -> list[Path]:
    """List production directories in stable lexical order."""
    base = Path(root)
    if not base.exists():
        return []
    return sorted((item for item in base.iterdir() if item.is_dir() and not item.name.startswith(".")), key=lambda p: p.name)


def create_production(root: str | Path, name: str) -> Path:
    """Create the production directory and its standard writable subdirs."""
    target = Path(root) / safe_production_name(name)
    target.mkdir(parents=True, exist_ok=False)
    for child in ("media", "takes", "out"):
        (target / child).mkdir()
    return target


def validate_production_file(path: str | Path) -> list[str]:
    """Return document validation errors without raising for user input."""
    source = Path(path)
    try:
        import yaml
        document: Any = yaml.safe_load(source.read_text())
    except (OSError, UnicodeError) as exc:
        return [f"cannot read {source}: {exc}"]
    except yaml.YAMLError as exc:
        return [f"invalid YAML: {exc}"]
    return validate_document(document)


def _require_fastapi() -> None:
    if FASTAPI_IMPORT_ERROR is not None:
        raise RuntimeError(
            "The web server requires optional dependencies. Install with "
            "`uv sync --extra web` (or `uv pip install -e '.[web]'`)."
        ) from FASTAPI_IMPORT_ERROR


def create_app(productions_root: str | Path | None = None, web_root: str | Path | None = None):
    """Build the FastAPI app, or fail explicitly when the web extra is absent.

    The productions root defaults to ``$IMPROMPTU_PRODUCTIONS`` so the container
    (which runs uvicorn directly against ``api.http:app``) serves the mounted
    host volume rather than a throwaway ``./videos`` inside the image.
    """
    _require_fastapi()
    if productions_root is None:
        productions_root = os.environ.get("IMPROMPTU_PRODUCTIONS", "videos")
    root = Path(productions_root)
    root.mkdir(parents=True, exist_ok=True)
    static_root = Path(web_root) if web_root else Path(__file__).parents[1] / "web"
    mcp_app = None
    try:
        from api.mcp import get_mcp
        mcp_app = get_mcp().http_app(path="/")
    except RuntimeError:
        # REST and the UI remain useful without the optional FastMCP package.
        pass
    app = FastAPI(title="impromptu studio", lifespan=mcp_app.lifespan if mcp_app else None)
    if mcp_app is not None:
        app.mount("/mcp", mcp_app)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/productions")
    async def productions() -> list[dict[str, str]]:
        return [{"name": item.name} for item in list_productions(root)]

    @app.post("/api/productions/{name}", status_code=201)
    async def new_production(name: str) -> dict[str, str]:
        try:
            target = create_production(root, name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail="production already exists") from exc
        return {"name": target.name}

    @app.post("/api/productions/{name}/uploads")
    async def upload(name: str, file: UploadFile = File(...)) -> dict[str, str]:
        try:
            production = root / safe_production_name(name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not production.is_dir():
            raise HTTPException(status_code=404, detail="production not found")
        payload = await file.read()
        digest = content_hash(payload)
        suffix = Path(file.filename or "upload.bin").suffix.lower()
        destination = production / "media" / f"{digest}{suffix}"
        destination.write_bytes(payload)
        return {"sha256": digest, "filename": destination.name, "bytes": str(len(payload))}

    @app.get("/api/productions/{name}/validate")
    async def validate(name: str) -> dict[str, Any]:
        try:
            production = root / safe_production_name(name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        path = production / "production.yaml"
        return {"valid": not validate_production_file(path), "errors": validate_production_file(path)}

    @app.websocket("/ws/teleprompter/{name}")
    async def teleprompter(websocket: WebSocket, name: str) -> None:
        await websocket.accept()
        await websocket.send_json({"type": "ready", "production": name, "paused": False, "position": 0})
        paused = False
        position = 0
        try:
            while True:
                message = await websocket.receive_json()
                action = message.get("action")
                if action == "pause":
                    paused = True
                elif action == "resume":
                    paused = False
                elif action == "toggle":
                    paused = not paused
                elif action == "seek":
                    position = max(0, int(message.get("position", position)))
                await websocket.send_json({"type": "state", "paused": paused, "position": position})
        except Exception:
            return

    if static_root.is_dir():
        app.mount("/static", StaticFiles(directory=static_root / "static"), name="static")

        @app.get("/")
        async def index():
            return FileResponse(static_root / "index.html")

    return app


__all__ = ["content_hash", "create_app", "create_production", "list_productions", "safe_production_name", "validate_production_file"]

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit("Run `impromptu serve`; do not execute api/http.py directly.")

# Keep the import boundary explicit for callers that expect an ASGI module.
app = None
if FASTAPI_IMPORT_ERROR is None:
    app = create_app()
