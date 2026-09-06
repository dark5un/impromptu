# Studio server

## Where things run

This machine splits the work across two environments, and mixing them up is the
most common way to lose an hour:

| | Environment | Home |
|---|---|---|
| The `impromptu` CLI, `pytest`, `ruff`, editing code | **distrobox** (`ai`) | `/var/home/panos/.distrobox/homes/ai` |
| `podman`, `systemctl --user`, quadlets, the studio service | **host** | `/var/home/panos` |

Rules that follow from it:

- Run every `podman` and `systemctl` command through **`distrobox-host-exec`**.
  A bare `podman build` inside distrobox writes to the container's own image
  store, which the host's systemd cannot see.
- **`%h` in a quadlet expands to the host home** (`/var/home/panos`), not to
  the container's `~`. `%h/workspace/videos` is a host path.
- The repo has two valid paths: `/run/host/var/home/panos/workspace/...` from
  distrobox, `/var/home/panos/workspace/...` on the host.
- `curl http://127.0.0.1:8787/...` works from either side, because the port is
  published on the host loopback and distrobox shares the host network
  namespace.
- Never fix a container permissions problem by changing host directory
  ownership — adjust the Containerfile's UID instead.

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
- `WS /ws/teleprompter/{name}` — `ready` carries the script and scene list;
  actions are pause/resume/toggle, seek, speed, `voice` and `follow`
- `POST /api/productions/{name}/render` (202 + job id) and
  `GET /api/renders[/{job_id}]` for queue state and progress
- `/mcp` when FastMCP is installed
- the plain ES-module UI at `/`, including voice-following prompter scroll

The container is intentionally explicit about its cost and inputs: Fedora 44 is
digest-pinned, MLT and RPM Fusion's full `ffmpeg` are installed, whisper.cpp is built from
source, and `/models/ggml-base.en.bin` is a required external model mount. The
HyperFrames Node 22/browser layer is adapted from the HyperFrames render
Containerfile. The image builds and was exercised directly: whisper-cli
transcribed a real take, HyperFrames rendered a real board, and the service
answered /healthz on a bind-mounted productions root.

**Verified as a live service 2026-09-07:** `studio.service` is installed as a
host systemd user unit and runs, serving `http://127.0.0.1:8787` on the mounted
host volume. `/healthz` → ok and a queued render completed `done` at 100%
(119/120 frames) writing a real 1920×1080 H.264+AAC master.

Three things had to be true before it could start, two known up front and one
discovered by actually starting it:

1. `Image=localhost/impromptu:latest` must exist (the host store builds
   `:f44`; it is tagged `:latest` as well).
2. `%h/workspace/videos` and `%h/workspace/impromptu-models` must exist on the
   host, or podman creates them root-owned and keep-id fails.
3. **The image must run its service as a non-root uid-1000 user.** The original
   image ran as root (`/root/.local/bin/uv`, chromium under `/root/.cache`);
   keep-id maps the container to host uid 1000, which cannot traverse root's
   0700 home, so the unit died instantly with `Permission denied`. The
   Containerfile now runs a `studio` uid-1000 account with `uv`/chromium
   relocated out of `/root` (see `docs/decisions.md`).

`quadlets/studio.container` expects `ai.network`, publishes only
`127.0.0.1:8787`, uses `UserNS=keep-id`, grants Chromium a 2 GiB shared-memory
segment, and persists `%h/workspace/videos` with SELinux relabeling.

## Verification

```bash
uv run pytest -q          # 202 passed, 0 skipped
uv run ruff check .
node --test tests/test_speech_matcher.mjs   # 16 passed
```

The tests verify the filesystem/hash/document helpers, the real WebSocket
contract via `fastapi.testclient`, the render queue, the vendored speech
matcher, pixel-truth board compositing, take-length validation, and the text
contracts of the Containerfile and quadlet.

`httpx` is in the dev group deliberately: without it every `TestClient` test
*silently skips*, which is how the teleprompter socket once shipped without
sending the script. Run `pytest -ra` occasionally to confirm nothing is being
skipped.

## Dependency failure behavior

Without the web extra, importing `api.http` still permits its pure helpers, but
`create_app()` and `impromptu serve` return an actionable `uv sync --extra web`
error. `api.mcp.get_mcp()` similarly raises an explicit FastMCP installation
error rather than silently faking MCP.

## Media note

Upload hashing is content-addressed but does not yet transcode or CFR-normalize
media — the plan's ingest normalization is still follow-up work.

Voice-following *is* implemented: recognition runs in the browser (Web Speech
API) and the matched position is reported over the socket, so the studio process
never handles audio. The matcher is vendored from
`jlecomte/voice-activated-teleprompter` (MIT) — see `web/static/vendor/NOTICE`.

## Container build status

The image builds and has been exercised end to end on the host as
`localhost/impromptu:f44`: `impromptu boards` → `render` → `package` produced a
329-frame master with libx264. See `docs/v2-traceability.md` for exactly which
parts are verified by real execution and which are still outstanding.

This project remains MIT; MLT is invoked as a subprocess rather than linked.
MLT licensing and the explicit encoder choice (RPM Fusion `ffmpeg` rather than
claiming libx264) are documented in `docs/decisions.md`.
