# impromptu v2 — plan-to-code traceability

Audit date: **2026-09-06**. Environment: Fedora 43 distrobox, Python 3.14.6,
MLT 7.36.1, ffmpeg 7.1.5 (`ffmpeg-free`), podman.

## How to read the verification class

| Class | Meaning |
|---|---|
| **runtime** | A command was executed in this environment and its real output inspected. For render work this means frames were extracted and looked at, not just frame counts compared. |
| **unit** | Covered by a test that exercises the code path with fixtures or an injected runner. No external binary involved. |
| **static** | A text/contract assertion only. Proves the file says something, not that it works. |
| **blocked** | Cannot be verified here; the exact blocker is named. |
| **deferred** | The source plan explicitly lists it as not built. |

A static contract is **never** reported as runtime verification.

---

## Phase 1 — document + MLT render

| Plan item | Implementation | Test | Class | Status |
|---|---|---|---|---|
| `docs/document-schema.md` normative | `docs/document-schema.md` | — | static | complete |
| Document load / validate / patch | `core/document.py` | `tests/test_document.py` | unit | complete |
| Required keys, unknown-key rejection | `core/document.py` `_unknown` | `test_unknown_top_level_key_is_rejected` | unit | complete |
| Media-name resolution | `core/document.py` | `test_overlay_must_resolve_named_media` | unit | complete |
| Document → MLT XML | `render/mlt_xml.py` | `tests/test_mlt.py`, `tests/test_compositor.py` | runtime | complete |
| `mlt-melt` subprocess, `real_time=-1`, threads | `render/melt.py` | `test_melt_command_is_deterministic` | runtime | complete |
| v1 → `production.yaml` migration | `core/migrate.py` | `tests/test_migrate.py` | unit | complete |
| Golden tests via framehash, never byte-compare | `tests/test_e2e_composite.py` | ffprobe assertions | runtime | complete |

**Phase 1 defects found and fixed** (all were green-suite blind spots):

1. `transition` was validated, written by `direct`, and documented — but never
   reached the XML. Every scene hard-cut.
2. `presenter: corner` / `hidden` likewise ignored: no PiP existed.
3. Overlay blanks were measured from zero instead of the previous entry's end,
   so a second board landed 300 frames late.
4. `render` handed MLT the authored board HTML, which it cannot decode.

## Phase 2 — closing the loop

| Plan item | Implementation | Test | Class | Status |
|---|---|---|---|---|
| whisper.cpp segment matching | `core/reconcile.py` | `tests/test_reconcile.py` | unit | complete |
| `measured_sec` per scene | `core/reconcile.py` | `test_reconcile_fixture_writes_...` | unit | complete |
| Scene-relative `segments` | `core/reconcile.py` | `test_leading_silence_anchors_...` | unit | complete |
| Fixture-based tests, no CI inference | `tests/test_reconcile.py` | injected script | unit | complete |
| `reconcile` CLI + drift report | `impromptu.py cmd_reconcile` | `tests/test_cli_v2.py` | unit | complete |
| Real whisper.cpp inference | `core/reconcile.py` `_run_whisper` | — | **blocked** | `whisper-cli` is not on the host PATH; it is built into the container image (verified present there). No model blob is bundled, so end-to-end transcription was not run. |

**Phase 2 defect found and fixed:** reconcile measured each scene from the
previous scene's end, so a take with leading silence produced
`segments[0].start > 0` — which `validate_document`'s own contiguity rule
rejects. Reconcile wrote documents its own loader refused to read.

## Phase 3 — boards via HyperFrames

| Plan item | Implementation | Test | Class | Status |
|---|---|---|---|---|
| `hyperframes render` command shape | `render/board.py hyperframes_command` | `tests/test_board.py` | unit | complete |
| Content-addressed cache (HTML + measured) | `render/board.py board_cache_key` | `tests/test_board.py` | unit | complete |
| Retake invalidates the cache | duration in the hash | `tests/test_board.py` | unit | complete |
| One-frame duration guard | `render/board.py validate_duration` | `tests/test_board.py` | unit | complete |
| Board resolves to `.mov` at render | `render/pipeline.py _resolve_boards` | `test_boards_resolve_to_the_rendered_mov...` | unit | complete |
| Unbuilt board is a named build error | `render/mlt_xml.py require_boards` | `test_render_refuses_a_production_whose...` | unit | complete |
| Starter templates + vertical variants | `render/board.py render_template` | `tests/test_board.py` | unit | complete |
| Local GSAP, no CDN | `render/board.py` template | `tests/test_board.py` | static | complete |
| ProRes 4444 alpha composites in MLT | `render/mlt_xml.py` | frame inspection | runtime | complete |
| Real HyperFrames board render | `render/board.py` | — | **blocked** | `hyperframes` and `bun` are absent from the host; the CLI is installed in the container image. The *artifact contract* (ProRes 4444 `yuva444p10le`, correct duration) was verified by feeding MLT an equivalent ffmpeg-produced ProRes 4444 file with real varying alpha. |

## Phase 4 — container

| Plan item | Implementation | Test | Class | Status |
|---|---|---|---|---|
| Fedora 43 digest-pinned | `containers/Containerfile` | `test_container_and_quadlet_contracts` | runtime | complete — image builds |
| MLT pinned | `dnf install mlt mlt-qt6` | in-image `mlt-melt -version` | runtime | 7.36.1 confirmed |
| Encoder decision explicit | `docs/decisions.md` | — | runtime | image has libx264, libopenh264, libvpx-vp9, prores_ks |
| whisper.cpp + `whisper-cli` | `containers/Containerfile` | `test_whisper_build_failure_is_not_swallowed` | runtime | `/usr/local/bin/whisper-cli` present |
| Model is a mount, not bundled | `/models/README` | — | static | complete |
| Fonts baked + `fc-cache -fv` | `containers/Containerfile` | — | runtime | 157 fonts in image |
| Node 22 + pinned headless shell | `hyperframes-render` stage | `test_headless_shell_path_is_resolved...` | runtime | complete |
| Quadlet network/ports/UserNS/`:Z`/shm | `quadlets/studio.container` | `test_quadlet_productions_env_matches...` | static | complete |
| Container service starts and serves | `quadlets/studio.container` | — | **blocked** | Not started as a systemd user service: that would install a unit into the user's live environment. The image builds and its binaries were exercised directly. |

**Phase 4 defects found and fixed:**

1. `PRODUCER_HEADLESS_SHELL_PATH` was set to `/opt/chrome-headless-shell`,
   which **does not exist in the image**. The `hf-render` wrapper resolved the
   real path, but `render/board.py` calls `hyperframes` directly and inherited
   the broken value, silently losing BeginFrame capture. The path is now
   resolved at build time and symlinked to a stable name.
2. The whisper.cpp build ended in `|| true`, so a compile failure would have
   shipped an image whose `reconcile` could never run.
3. `IMPROMPTU_PRODUCTIONS` was declared in the quadlet and read by **nothing** —
   the container's uvicorn entrypoint served a throwaway `./videos` inside the
   image instead of the mounted host volume.

## Phase 5 — web UI + MCP

| Plan item | Implementation | Test | Class | Status |
|---|---|---|---|---|
| `/healthz` | `api/http.py` | `tests/test_phase45_contracts.py` | runtime | 200 `{"status":"ok"}` |
| Production list / create | `api/http.py` | `tests/test_phase45_contracts.py` | runtime | 201; duplicate → 409 |
| Upload hashed into `media:` | `api/http.py upload` | `test_upload_hash_is_content_addressed` | runtime | sha256 filename confirmed |
| Path-traversal rejection | `safe_production_name` | `test_safe_production_name_rejects...` | runtime | `..%2Fetc` rejected |
| WebSocket teleprompter | `api/http.py teleprompter` | — | runtime | pause / resume / toggle / seek all correct |
| Static UI served | `web/index.html`, `web/static/app.js` | `test_web_ui_contains_api...` | runtime | `GET /` 200 |
| FastMCP mounted in-process | `api/mcp.py` | `test_mcp_has_explicit_optional_dependency_boundary` | runtime | mounts at `/mcp`; 3 tools listed |
| Actionable error without FastMCP | `api/mcp.py _require_fastmcp` | same | unit | complete |
| Productions root from environment | `api/http.py create_app` | `test_productions_root_is_configurable...` | runtime | complete |
| Voice-following prompter | — | — | **not built** | The prompter is manual pause/resume/seek over WebSocket. Plan item 14 (fork `jlecomte/voice-activated-teleprompter`, voice-following scroll, phone-as-remote QR) is **not implemented**. `impromptu pair` prints a token and URL but no `/remote` route serves it. |
| ~12 intent-shaped MCP tools | `api/mcp.py` | — | **partial** | 3 tools exist (`list_productions`, `validate_document`, `create_production`). The plan's `doc.patch`, `reconcile.run`, `direct.run`, `render.start`, `package.run` are absent. |
| Render queue with progress | — | — | **not built** | `render/melt.py` parses progress, but no queue or API surface exposes it. |

## Deferred by the source plan (correctly not built)

Phrase-level CTC forced alignment · separate materialised EDL · OTIO export ·
in-browser MediaRecorder capture · multi-presenter · TTS voiceover (v1's Kokoro
path remains available as `impromptu tts`).

---

## Honest summary

**Verified by real execution:** the MLT compositor (transitions, PiP, z-order,
alpha, frame-exact programme length), the document/migrate/reconcile core, the
board artifact and caching contracts, the container image build and its
binaries, and the full HTTP + WebSocket + MCP surface.

**Blocked, with named blockers:** real whisper transcription and a real
HyperFrames browser render (both tools live in the container, not on the host);
starting the quadlet as a live user service.

**Genuinely incomplete:** Phase 5's voice-following teleprompter, the phone
remote route, the render queue, and 9 of the 12 planned MCP tools. These are
the honest remaining gaps against the source plan.
