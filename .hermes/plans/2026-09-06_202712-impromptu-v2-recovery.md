# impromptu v2 Recovery and Completion Plan

> **For Hermes:** Use this plan to audit the existing implementation first, then continue only from verified facts. Do not trust historical async-worker summaries without reproducing their claims against the live repository.

**Goal:** Evaluate the implementation of `2026-09-06_impromptu-v2-lean.md`, separate completed work from contract-only or unverified work, and finish the remaining product-critical integrations without claiming success that has not been exercised.

**Architecture:** Keep `production.yaml` as the sole editable production decision artifact. Preserve the v1 CLI and its behavior. Use stdlib/XML generation plus the external `mlt-melt` subprocess; use HyperFrames as an external board renderer; keep FastAPI/FastMCP optional at the Python boundary and provide the full runtime through the container.

**Tech Stack:** Python 3.14/3.12 compatibility, PyYAML, pytest, Ruff, uv, MLT/`mlt-melt`, ffmpeg/ffprobe, whisper.cpp, HyperFrames, FastAPI, FastMCP, Podman, Quadlet.

---

## 0. Rules for this recovery

1. Work from the live filesystem, not from async reports or compacted summaries.
2. Before changing anything, record `git status`, `git log`, the current test count, and the current CLI help output.
3. Never reset or discard existing work. Treat `.hermes/` as planning metadata unless the user explicitly asks to commit it.
4. For every claimed feature, distinguish:
   - **implemented and unit-tested**;
   - **integration-tested locally**;
   - **blocked by unavailable external tooling**;
   - **intentionally deferred by the source plan**.
5. Use RED → GREEN → REFACTOR for missing behavior. Add a failing test before implementation whenever the behavior is not already covered.
6. Run lint/static checks before tests after each logical work unit, then run the full suite and an ad-hoc probe.
7. Commit only coherent, verified logical units. Never commit generated caches, credentials, model files, or `.venv`.

---

## 1. Establish the actual baseline

**Objective:** Replace contradictory historical reports with one reproducible baseline.

**Read/inspect:**
- `/run/host/var/home/panos/workspace/github.com/dark5un/impromptu/.hermes/plans/2026-09-06_impromptu-v2-lean.md`
- `README.md`
- `docs/document-schema.md`
- `docs/studio.md`
- `docs/decisions.md`
- `pyproject.toml`, `requirements*.txt`, `uv.lock`
- `impromptu.py`
- `core/*.py`, `render/*.py`, `api/*.py`
- `containers/Containerfile`, `quadlets/studio.container`
- all `tests/*.py`

**Run from the repository root:**

```bash
git status --short --branch && git log --oneline -10 && \
python3 -m pytest tests/ -q && \
python3 -m ruff check . && \
python3 -m compileall -q core render api impromptu.py && \
for command in validate migrate reconcile direct boards render package pair serve; do python3 impromptu.py "$command" --help >/dev/null || exit 1; done
```

**Record explicitly:**
- exact test count and failures;
- exact tracked/untracked modifications;
- whether the current branch contains the intended commits;
- which tests are contract/text tests versus real subprocess/integration tests;
- whether the current Python environment has FastAPI/FastMCP, `whisper-cli`, HyperFrames, `mlt-melt`, ffmpeg, ffprobe, Podman, and uv.

**Acceptance:** A dated baseline report is written in the final implementation notes or a new audit document; no implementation changes are made during this step.

---

## 2. Build a plan-to-code traceability matrix

**Objective:** Determine what the original plan actually requires and whether the repository delivers it.

Create `docs/v2-traceability.md` with a table containing:

| Plan item | Implementation | Test | Verification class | Status | Gap/action |
|---|---|---|---|---|---|

Cover at least:

- document schema, null pre-directing fields, unknown-key rejection, media-name resolution;
- deterministic MLT XML, transitions, PiP, audio mixing, frame timing, and `mlt-melt` invocation;
- v1 migration and preservation of v1 commands;
- Whisper fixture reconciliation, scene-relative segments, drift report, rerun behavior;
- directorial defaults and human review checkpoint;
- HyperFrames project/composition invocation, ProRes 4444 alpha, local GSAP, starter templates, cache invalidation, one-frame duration guard;
- container dependencies and explicit encoder decision;
- Quadlet network, ports, `UserNS`, volumes, SELinux labels, and shared memory;
- FastAPI health/list/create/upload/WebSocket/pairing behavior;
- FastMCP real optional integration and actionable missing-dependency error;
- web UI behavior;
- render/package artifacts and the manual-upload boundary;
- explicit deferred work from the source plan.

**Acceptance:** Every Phase 1–5 item is marked `complete`, `partial`, `blocked`, or `deferred`, with a file/test/command proving the status. Do not mark a text contract as runtime verification.

---

## 3. Close correctness gaps in the production document and reconciliation

**Objective:** Ensure the canonical document is safe as the only editable artifact.

**Tests first:** Extend or add tests in:
- `tests/test_document.py`
- `tests/test_migrate.py`
- `tests/test_reconcile.py`

Cover:
1. pre-directing `presenter: null` and `transition: null` are accepted, while directed invalid values fail;
2. segment starts are non-negative and contiguous, segment ends are ordered, and the final segment ends at `measured_sec` where required;
3. rerunning reconciliation replaces stale measured values and segments rather than accumulating them;
4. unmatched transcript text and empty scenes produce a deterministic, documented result;
5. scenes with pauses/gaps do not create negative relative offsets;
6. planned/measured drift uses a stable report format;
7. migration rejects mismatched scene counts and invalid/non-contiguous v1 timings with useful errors;
8. integer graphic indices map deterministically to named media and output passes the same validator as hand-authored documents.

**Implementation:**
- `core/document.py`
- `core/migrate.py`
- `core/reconcile.py`
- `impromptu.py`
- documentation for any deliberately unsupported input.

**Verification:** lint/static checks first; focused tests; full tests; a temporary end-to-end migration → fixture reconciliation → validation → drift-report probe.

**Acceptance:** `production.yaml` is the only decision file modified by these commands, and the probe can be repeated idempotently.

---

## 4. Close MLT and render pipeline correctness gaps

**Objective:** Verify that generated XML actually represents the validated document and that the render/package pipeline does not merely satisfy mocks.

**Tests first:** Extend:
- `tests/test_mlt.py`
- `tests/test_v2_integration.py`
- add `tests/test_mlt_media_probe.py` if needed.

Cover:
1. first-scene cut and later transition types, including zero-duration cuts;
2. transition duration/frame accounting and final tractor duration;
3. overlays present in only some scenes;
4. presenter audio remains audible under overlays through an explicit mix transition;
5. board media resolves to the rendered `.mov` artifact, not the source HTML, during render;
6. missing media and missing `production.yaml` fail clearly;
7. injected runner receives the documented `mlt-melt`, `real_time=-1`, and thread arguments;
8. packaging refuses absent render output, writes loudnorm/thumbnail/chapters/description/checklist, and never uploads.

**Implementation:**
- `render/mlt_xml.py`
- `render/melt.py`
- `render/pipeline.py`
- `core/direct.py`
- `impromptu.py`

**Real probe:** Generate tiny synthetic presenter/board/audio fixtures with ffmpeg where available. Run the XML through `mlt-melt`, then inspect with `ffprobe`; use framehash or structural/frame-count checks, never MP4 byte comparison. If the host lacks a required MLT producer/encoder, record the exact blocker and keep the fixture test deterministic.

**Acceptance:** The code either performs a real small render or documents a precise environment blocker; it must not claim a successful real render from an injected/mock runner.

---

## 5. Fix and verify HyperFrames integration

**Objective:** Make the board renderer match the official local HyperFrames CLI and prove the artifact contract where the tool is available.

**Current contract to preserve:**

```text
hyperframes render <project-directory> \
  --composition <composition-file> \
  --output <board.mov> \
  --format mov \
  --fps <fps>
```

The expected MOV encoder is ProRes 4444 with `prores_ks`, `yuva444p10le`, profile 4444, and vendor `apl0`.

**Tests first:** Extend `tests/test_board.py` to cover:
- project-directory plus `--composition` command shape;
- nested composition path handling;
- root duration extraction failures;
- one-frame tolerance boundary and rejection beyond it;
- content hash changes for HTML bytes and measured duration;
- stale cache invalidation;
- every starter template’s landscape/vertical dimensions, local GSAP path, required `clip` attributes, and paused `window.__timelines["main"]` registration;
- board registration in document media for downstream MLT.

**Implementation:**
- `render/board.py`
- `tests/test_board.py`
- `impromptu.py`
- `README.md`, `docs/document-schema.md`, `docs/studio.md`

**Runtime probe:** In the HyperFrames clone, use the checked-in source and, if dependencies/build artifacts are available, render one starter composition to MOV. Verify with `ffprobe`:

```bash
ffprobe -v error -show_streams -show_format -of json board.mov
```

Require a video stream with the expected frame rate, duration within one frame, ProRes 4444/alpha pixel format, and an output produced from the composition rather than a still screenshot. If HyperFrames/Bun dependencies are unavailable, record that as blocked and do not report success.

**Acceptance:** Unit tests validate command construction; a real renderer invocation is separately labeled verified or blocked.

---

## 6. Complete container/Quadlet verification without false claims

**Objective:** Make the runtime image reproducible and determine whether it can actually be built and started.

**Static audit:**
- `containers/Containerfile` must have a digest-pinned Fedora base;
- MLT package choice/version and ffmpeg encoder decision must be explicit;
- whisper.cpp build must expose `whisper-cli` and use an external model mount/placeholder;
- Node 22 and the HyperFrames render layer must be copied into the runtime image;
- chrome-headless-shell path and `PRODUCER_HEADLESS_SHELL_PATH` must be explicit;
- fonts must be installed and `fc-cache -fv` run;
- local GSAP must be available to the renderer;
- Python web dependencies must be installed through project metadata;
- no credentials or model blobs are copied into the image.

**Quadlet audit:**
- `Network=ai.network`;
- `UserNS=keep-id`;
- `PublishPort=127.0.0.1:8787:8787`;
- `%h/workspace/videos` and model mounts use `:Z` where required;
- shared memory is 2 GiB;
- restart policy and container name are explicit;
- comments may document image-provided MLT/ffmpeg/whisper/browser components but must not substitute for runtime behavior.

**Tests:**
- `tests/test_phase45_contracts.py` for static contracts;
- add a parser/static test if a required field is currently only checked by substring.

**Build matrix:**
1. `podman build --file containers/Containerfile --tag localhost/impromptu:verification .`
2. If rootless nested build fails, try the supported host/rootful or non-nested environment; do not weaken the Containerfile solely to satisfy the nested host.
3. If build succeeds, run the image with isolated temporary volumes and check:

```bash
curl -fsS http://127.0.0.1:8787/healthz
```

4. Inspect installed versions and executable paths inside the image.
5. Do not publish or deploy automatically.

**Acceptance:** The result is one of `runtime verified`, `blocked with exact reproducible error`, or `Containerfile corrected and build pending`. Documentation must state which one applies.

---

## 7. Verify the optional FastAPI/FastMCP boundary and web UI

**Objective:** Separate pure API correctness from optional dependency/runtime correctness.

**Tests first:** Extend:
- `tests/test_phase45_contracts.py`
- add `tests/test_api_runtime.py` where dependencies are installable.

Cover:
1. pure upload hashing and path traversal rejection;
2. production directory listing/creation and validated document writes;
3. `/healthz` response;
4. WebSocket state/control messages: pause, resume, toggle, seek, speed;
5. pairing token creation/validation and expiry semantics;
6. static UI loads and calls the expected endpoints;
7. `api.mcp.get_mcp()` returns a real FastMCP object when installed;
8. `api.mcp.get_mcp()` raises an explicit actionable error when FastMCP is unavailable;
9. the service does not silently fake MCP or upload videos automatically.

**Implementation:**
- `api/http.py`
- `api/mcp.py`
- `web/index.html`
- `web/static/app.js`
- `impromptu.py`
- `docs/studio.md`

**Runtime verification:** Use the project web extra in an isolated uv environment. Start the app with a temporary video root, query `/healthz`, exercise one API request and one WebSocket session, and stop it. Do not touch the user’s existing service/configuration.

**Acceptance:** FastAPI/FastMCP runtime is either exercised successfully in isolation or documented as blocked with the exact dependency/runtime error.

---

## 8. Align documentation and remove misleading completion claims

**Objective:** Make the repository tell the truth about what is implemented, tested, blocked, and deferred.

Review/update:
- `README.md`
- `docs/document-schema.md`
- `docs/studio.md`
- `docs/decisions.md`
- this recovery plan’s traceability matrix or a companion audit

Required documentation:
- canonical `production.yaml` workflow;
- exact CLI argument shapes from `--help`;
- HyperFrames composition/project invocation;
- ProRes/alpha choice and why WebM is not used for final boards;
- MLT subprocess/licence boundary;
- manual upload boundary;
- container verification status;
- optional dependency behavior;
- explicit deferred work: CTC alignment, separate EDL, OTIO, browser MediaRecorder capture, multi-presenter, TTS unless deliberately ported.

**Acceptance:** No document claims a real container, real board render, real Whisper inference, or real service runtime was verified unless a command produced evidence in the current environment.

---

## 9. Final verification and delivery

Run, in order:

```bash
python3 -m ruff check . && \
python3 -m compileall -q core render api impromptu.py && \
python3 -m pytest tests/ -q && \
python3 -m pytest tests/test_document.py tests/test_mlt.py tests/test_migrate.py tests/test_reconcile.py tests/test_board.py tests/test_v2_integration.py tests/test_phase45_contracts.py -q && \
for command in validate migrate reconcile direct boards render package pair serve; do python3 impromptu.py "$command" --help >/dev/null || exit 1; done && \
git diff --check && git status --short --branch
```

Then run the ad-hoc probes that are possible in the current environment:
- migration → validation → fixture reconciliation → direct → boards with an injected runner;
- XML generation and any available real `mlt-melt` render;
- HyperFrames starter render if the local clone can run it;
- isolated API `/healthz` and WebSocket probe if web extras are available;
- container build/start probe if the host permits it.

Before each commit:
- inspect the staged diff;
- ensure no credentials, caches, `.venv`, model files, or generated media are staged;
- run `git diff --cached --check`;
- commit one logical work unit with a precise message.

Final report must include:
- plan-to-code matrix path;
- commits created;
- exact tests/lint/compile/probe results;
- runtime integrations verified;
- runtime integrations blocked and exact errors;
- deferred items;
- remaining work, if any.

**Definition of done:** Every original plan item has a traceable implementation and test or an explicit blocked/deferred status, the repository is green, docs are honest, and no external integration is described as complete without execution evidence.
