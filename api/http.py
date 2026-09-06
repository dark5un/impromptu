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
from core.pairing import DEFAULT_TTL_SECONDS, PairingStore

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


def prompter_payload(path: str | Path) -> dict[str, Any]:
    """Return the script the prompter follows, plus its scene boundaries.

    Voice-following is impossible unless the browser has the words to match
    speech against, and the previous socket sent only playback state. The
    script is assembled from each scene's ``say`` so it stays the single source
    of truth in the document -- there is no second copy to drift.
    """
    import yaml

    document: Any = yaml.safe_load(Path(path).read_text())
    if not isinstance(document, dict):
        raise TypeError(f"{path} is not a production document")
    scenes = []
    for scene in document.get("scenes") or []:
        say = (scene.get("say") or "").strip()
        scenes.append({"id": scene.get("id"), "say": say,
                       "planned_sec": scene.get("planned_sec")})
    return {
        "title": document.get("title"),
        # Blank line between scenes: the prompter shows a visible beat where a
        # scene ends, and the tokenizer treats it as a delimiter either way.
        "script": "\n\n".join(scene["say"] for scene in scenes if scene["say"]),
        "scenes": scenes,
    }


def _require_fastapi() -> None:
    if FASTAPI_IMPORT_ERROR is not None:
        raise RuntimeError(
            "The web server requires optional dependencies. Install with "
            "`uv sync --extra web` (or `uv pip install -e '.[web]'`)."
        ) from FASTAPI_IMPORT_ERROR


def create_app(productions_root: str | Path | None = None, web_root: str | Path | None = None,
               *, require_pairing: bool = False):
    """Build the FastAPI app, or fail explicitly when the web extra is absent.

    The productions root defaults to ``$IMPROMPTU_PRODUCTIONS`` so the container
    (which runs uvicorn directly against ``api.http:app``) serves the mounted
    host volume rather than a throwaway ``./videos`` inside the image.

    *require_pairing* additionally gates the teleprompter socket on a token, for
    when the studio is reachable from more than localhost.
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
    app.state.pairing = PairingStore()
    app.state.require_pairing = require_pairing
    from api.queue import RenderQueue
    app.state.renders = RenderQueue()
    if mcp_app is not None:
        app.mount("/mcp", mcp_app)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/pair", status_code=201)
    async def pair() -> dict[str, Any]:
        """Mint a pairing token for the phone remote."""
        return {"token": app.state.pairing.issue(), "ttl_seconds": DEFAULT_TTL_SECONDS}

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

    @app.post("/api/productions/{name}/render", status_code=202)
    async def start_render(name: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        """Queue a render and return immediately with a job id.

        202 rather than 200: the render has been accepted, not completed. Poll
        ``/api/renders/{job_id}`` for progress.
        """
        try:
            production = root / safe_production_name(name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not (production / "production.yaml").is_file():
            raise HTTPException(status_code=404, detail="production not found")
        threads = int((body or {}).get("threads", 1))
        job_id = app.state.renders.submit(production, threads=threads)
        return {"job_id": job_id, "state": "queued"}

    @app.get("/api/renders")
    async def list_renders() -> list[dict[str, Any]]:
        return app.state.renders.list()

    @app.get("/api/renders/{job_id}")
    async def render_status(job_id: str) -> dict[str, Any]:
        job = app.state.renders.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="unknown render job")
        return job

    @app.websocket("/ws/teleprompter/{name}")
    async def teleprompter(websocket: WebSocket, name: str) -> None:
        if app.state.require_pairing and not app.state.pairing.validate(
                websocket.query_params.get("token")):
            await websocket.close(code=1008)
            return
        await websocket.accept()
        # Send the script before anything else: the browser cannot follow the
        # voice without the words, and an unknown production must say so rather
        # than silently prompt an empty script.
        try:
            production = root / safe_production_name(name)
            payload = prompter_payload(production / "production.yaml")
        except (TypeError, ValueError, OSError) as exc:
            await websocket.send_json({
                "type": "error",
                "detail": f"cannot load production {name!r}: {exc}",
            })
            await websocket.close(code=1011)
            return
        speed = 1.5
        paused = False
        position = 0
        # Following starts off: the speaker opts in when recognition starts, so
        # merely opening the page does not imply microphone use.
        following = False
        await websocket.send_json({
            "type": "ready", "production": name, "paused": paused,
            "position": position, "speed": speed, "following": following,
            "title": payload["title"], "script": payload["script"],
            "scenes": payload["scenes"],
        })
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
                elif action == "voice":
                    # The browser owns speech recognition and matching; the
                    # server records the matched token index it reports.
                    position = max(0, int(message.get("position", position)))
                    following = True
                elif action == "follow":
                    # Explicit way back after a manual override.
                    following = True
                elif action == "seek":
                    position = max(0, int(message.get("position", position)))
                    # Plan item 14: manual control is an override, so a hand
                    # seek stops voice-following from fighting it.
                    following = False
                elif action == "speed":
                    # Clamped to the same range as the terminal prompter.
                    speed = max(0.3, min(10.0, float(message.get("speed", speed))))
                    following = False
                await websocket.send_json({"type": "state", "paused": paused,
                                           "position": position, "speed": speed,
                                           "following": following})
        except Exception:
            return

    if static_root.is_dir():
        app.mount("/static", StaticFiles(directory=static_root / "static"), name="static")

        @app.get("/")
        async def index():
            return FileResponse(static_root / "index.html")

        @app.get("/remote")
        async def remote(token: str | None = None):
            """Serve the phone remote for a token minted by `impromptu pair`.

            A missing token is 401 (you did not present one) and an unknown or
            expired token is 403 (you presented one and it is not valid), so the
            failure tells you which mistake you made.
            """
            if not token:
                raise HTTPException(status_code=401, detail="pairing token required")
            if not app.state.pairing.validate(token):
                raise HTTPException(status_code=403, detail="invalid or expired pairing token")
            remote_page = static_root / "remote.html"
            if not remote_page.is_file():
                raise HTTPException(status_code=404, detail="remote UI is not installed")
            return FileResponse(remote_page)

    return app


__all__ = ["content_hash", "create_app", "create_production", "list_productions", "safe_production_name", "validate_production_file"]

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit("Run `impromptu serve`; do not execute api/http.py directly.")

# Keep the import boundary explicit for callers that expect an ASGI module.
app = None
if FASTAPI_IMPORT_ERROR is None:
    app = create_app()
