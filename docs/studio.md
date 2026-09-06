# Studio server

Phase 4-5 adds a local FastAPI studio surface and an optional FastMCP endpoint.
The base CLI remains usable with only PyYAML. Install the server dependencies with
`uv sync --extra web` (or `uv pip install -r requirements-web.txt`). FastMCP is a
real optional dependency; it is never replaced with a compatibility stub.

```bash
uv sync --extra web
impromptu serve --videos "$HOME/workspace/videos" --host 127.0.0.1 --port 8787
curl http://127.0.0.1:8787/healthz
```

The server provides:

- `GET /healthz`
- `GET /api/productions` and `POST /api/productions/{name}`
- `POST /api/productions/{name}/uploads`, storing SHA-256-addressed media
- `GET /api/productions/{name}/validate`, backed by `core.document`
- `WS /ws/teleprompter/{name}` with ready/state, pause/resume/toggle, and seek
- `/mcp` when FastMCP is installed
- the plain ES-module UI at `/`

The container is intentionally explicit about its cost and inputs: Fedora 43 is
digest-pinned, MLT and `ffmpeg-free` are installed, whisper.cpp is built from
source, and `/models/ggml-base.en.bin` is a required external model mount. The
HyperFrames Node 22/browser layer is adapted from the HyperFrames render
Containerfile. The image has not been claimed as built here; build it in an
environment with Podman and network access before deploying the quadlet.

`quadlets/studio.container` expects `ai.network`, publishes only
`127.0.0.1:8787`, uses `UserNS=keep-id`, grants Chromium a 2 GiB shared-memory
segment, and persists `%h/workspace/videos` with SELinux relabeling.

## Verification

```bash
uv run pytest -q
uv run ruff check .
```

The current tests verify pure filesystem/hash/document helpers, the WebSocket
contract, UI hooks, and the text contracts of the Containerfile and quadlet.
They do not claim a successful image build.

## Dependency failure behavior

Without the web extra, importing `api.http` still permits its pure helpers, but
`create_app()` and `impromptu serve` return an actionable `uv sync --extra web`
error. `api.mcp.get_mcp()` similarly raises an explicit FastMCP installation
error rather than silently faking MCP.

## Media note

Upload hashing is content-addressed but does not yet transcode or CFR-normalize
media. The plan's ingest normalization and voice-following transcription remain
follow-up work; this slice only implements the minimal teleprompter control
channel.

## Container build status

Not run as part of this change: the Fedora/Node multi-stage build needs network,
RPM repositories, and a large browser/model toolchain. Do not treat the
Containerfile as a verified image until `podman build` completes locally.

This project remains MIT; MLT is invoked as a subprocess rather than linked.
MLT licensing and the explicit encoder choice (`ffmpeg-free` rather than
claiming libx264) are documented in `docs/decisions.md`.
