# impromptu v2 — plan-to-code traceability

Audit date: **2026-09-06**. Host: Fedora 43 distrobox, Python 3.14.6,
MLT 7.36.1, ffmpeg 7.1.5 (`ffmpeg-free`), podman. Container: Fedora 44,
MLT 7.40.0, RPM Fusion ffmpeg with libx264.

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
| Real whisper.cpp inference | `core/reconcile.py` `_run_whisper` | — | **runtime** | complete — `whisper-cli` with `ggml-tiny.en` transcribed three spoken sentences in the image; reconcile measured 4.08/4.40/3.52s against planned 4.0/4.5/3.5s |

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
| Local GSAP vendoring | `render/board.py vendor_gsap` | `tests/test_board.py` | runtime | complete |
| Real HyperFrames board render | `render/board.py` | — | **runtime** | complete — HyperFrames 0.8.30 rendered `drift.html` in the image to ProRes 4444 `yuva444p12le`, 132 frames / 4.400s matching `measured_sec`, alpha varying 256-3773, four distinct frame hashes proving the GSAP timeline animates |

## Phase 4 — container

| Plan item | Implementation | Test | Class | Status |
|---|---|---|---|---|
| Fedora digest-pinned | `containers/Containerfile` | `test_container_and_quadlet_contracts` | runtime | complete — F44 pinned; MLT 7.40.0 verified byte-identical to F43's 7.36.1 (SSIM 1.000000 all planes) |
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
| Voice-following prompter | `web/static/vendor/speech-matcher.js`, `api/http.py` | `tests/test_speech_matcher.mjs`, `tests/test_prompter_and_queue.py` | runtime | complete — matcher ported from `jlecomte/voice-activated-teleprompter` (MIT, attributed in `web/static/vendor/NOTICE`); socket now serves the script and tracks matched positions, with manual speed/seek as an override. Verified against a live uvicorn: `ready` carried the real 3-scene script, `voice` → `following: true`, `speed` → `following: false`, `follow` → back on. |
| Phone remote + pairing | `core/pairing.py`, `/remote`, `/api/pair` | `tests/test_pairing.py` | runtime | complete — `impromptu pair` mints a token from the running studio and the printed URL opens the remote |
| ~12 intent-shaped MCP tools | `api/mcp.py` | `tests/test_mcp_tools.py` | runtime | complete — 12 tools (`read_document`, `patch_document`, `reconcile_run`, `direct_run`, `scene_layout`, `drift_report`, `boards_build`, `render_start`, `package_run`, plus discovery/validation), exercised against the real end-to-end production |
| Render queue with progress | `api/queue.py`, `api/http.py` | `tests/test_prompter_and_queue.py` | runtime | complete — single-worker queue reusing `run_melt(on_progress=...)`; `POST /api/productions/{name}/render` → 202 + job id, `GET /api/renders[/{id}]` to poll. Verified against a live server: a real mlt-melt render reported `0.0% → 40.2% → 60.1% → 100%` across frames 0→328 of 336. |

## End-to-end chain (verified 2026-09-06)

The whole loop was exercised once with real tools rather than fixtures, which
is what surfaced the `hyperframes` bin, GSAP vendoring, 48kHz, and thumbnail
defects — all four passed unit tests and would have failed on a real video.

| Stage | Evidence |
|---|---|
| Spoken take | Three `flite` sentences concatenated to 11.77s, 48kHz |
| Real transcription | `whisper-cli` + `ggml-tiny.en` in the image returned three segments |
| `reconcile` | measured 4.08 / 4.40 / 3.52s; drift +0.08 / -0.10 / +0.02s |
| `direct` | chose `corner` for the board scene, `fullscreen` either side |
| Board authored to measurement | `data-duration="4.4"`, GSAP beats at 1.32s and 2.42s |
| Real board render | HyperFrames 0.8.30 → ProRes 4444, 132 frames / 4.400s, alpha 256-3773 |
| `render` | `mlt-melt` → 329 frames / 10.99s, 1920x1080, CFR 30 |
| `package` | 48kHz master, 1280x720 thumbnail, chapters 00:00 / 00:04 / 00:08 |
| Frame inspection | presenter fullscreen → PiP with board → bars animating 0→18% and 0→35→94% → fullscreen outro |

## Deferred by the source plan (correctly not built)

Phrase-level CTC forced alignment · separate materialised EDL · OTIO export ·
in-browser MediaRecorder capture · multi-presenter · TTS voiceover (v1's Kokoro
path remains available as `impromptu tts`).

---

## Honest summary

**Verified by real execution:** the full production chain, end to end, with
real tools — spoken take → whisper transcription → reconcile → direct → board
authored to the measurement → HyperFrames browser render → MLT composite →
package, with the output inspected frame by frame. Plus the MLT compositor
(transitions, PiP, z-order, alpha, frame-exact length), the container image and
its binaries, and the HTTP + WebSocket + MCP + pairing surface.

**Blocked, with a named blocker:** starting the quadlet as a live systemd user
service, which would install a unit into the user's environment. The image
builds and was run directly instead.

**Genuinely incomplete:** nothing remaining against the source plan's built
scope. Voice-following scroll and the render queue — the two gaps this document
previously listed — are implemented and verified against a live server. The
matching algorithm was **ported, not reinvented**, from
`jlecomte/voice-activated-teleprompter` (MIT), which exists precisely because
naive prompters stall when you go off script; only its three pure functions
came over, since impromptu's UI is bundler-free and the upstream is a
React/Redux/Vite app.

**Also fixed:** a take shorter than its own timeline was silently truncated —
the demo's final scene lost 7 frames with a zero exit status, and every
structural assertion passed. `render/take.py` now validates take length before
`mlt-melt` runs, measuring *take* time rather than programme time so transition
overlaps cannot excuse a short recording. Verified on the production that
produced the defect, host and container identical: it now fails with the scene,
the 0.23s shortfall, and the fix, exiting 1. Write-up in
`docs/fixed-take-shorter-than-timeline.md`; nine regression tests assert on the
error rather than on frame counts.

**Testing gap closed:** `httpx` was missing from the dev group, so every
`fastapi.testclient` test *silently skipped*. That is why the teleprompter
socket shipped without ever having been exercised. It is now a dev dependency.

**Fixed since the audit:** the comb artifact was an **alpha convention**
mismatch, not interpolated `affine` keyframes as first diagnosed. HyperFrames
writes straight alpha; MLT consumes it as premultiplied, so every
semi-transparent pixel composited at full intensity (the bar track went white,
and anti-aliased edges lost their gradient, which is what looked like a comb).
Boards are now premultiplied at build time. Board-region mean abs error against
the source board fell 39.318 → 1.167 and the bar track reads `[25,25,25]`
against an expected 26. Evidence, the three configurations that disproved the
original diagnosis, and the lesson are in
`docs/fixed-board-alpha-convention.md`; regression tests are pixel-truth in
`tests/test_alpha_compositing.py`.

**Also fixed, both found only by running the container:** `--fps 30.0` was
rejected by HyperFrames ("Invalid fps") so no real board render ever succeeded,
and `impromptu boards` wrote to `out/boards` while `render` reads
`.cache/boards`, so the two documented halves of the workflow disagreed on a
path. Both had passing unit tests.

**Lesson worth keeping:** ten defects were found in this audit. Six of them —
the compositor's missing transitions and PiP, the board HTML reaching MLT, the
broken `hyperframes` bin, unvendored GSAP, and the 48kHz regression — passed a
green test suite and were only exposed by running real tools and looking at
real output. Frame counts were not enough; several bugs rendered "successfully"
and were only visible in the pixels.
