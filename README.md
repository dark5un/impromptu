# impromptu

Terminal teleprompter + agent-driven YouTube video pipeline
(presenter + motion graphics + packaging).

```
You + Hermes brainstorm narrative
        |
        v
Hermes writes script.md (with scene timing)
        |
        +--> YOU: impromptu script.md --> read on camera --> presenter_raw.mp4
        +--> Hermes: HyperFrames HTML compositions per scene
        +--> Hermes: scene-plan.json from script timing
                 |
                 v
         Mode A (ffmpeg stitch):  impromptu composite plan.json -p presenter.mp4 -g g0.mp4 ... -o final.mp4
         Mode B (single render):  impromptu build-hf plan.json -p presenter.mp4 -o hf_project/ && impromptu render-hf hf_project/ -o final.mp4
                 |
                 v
         impromptu package final.mp4 --plan plan.json --> loudnorm master + chapters + thumbnail + description (+ Shorts + TTS)
```

## Modes

- **Mode A (ffmpeg stitch):** per-scene HyperFrames renders, stitched with ffmpeg
  (fixed chained-xfade offsets, plan validation, CFR output). Best for quick
  turnaround and ffmpeg-only effects (chromakey). `composite` also accepts
  `--graphics-track` (one full-length Mode B graphic, scenes reference time
  ranges) and `--normalize` (VFR phone footage to CFR first).
- **Mode B (default, single render):** `build-hf` generates ONE HyperFrames
  project (`index.html` with presenter a-roll + overlay clips, one paused GSAP
  timeline) and bundles the presenter into the project dir; `render-hf` renders
  it ONCE via the one-shot `localhost/hyperframes-render:latest` container.
  No per-scene MP4s, no xfade chain.

## Requirements

- Python 3 (stdlib only, no dependencies)
- FFmpeg 7+ with ffprobe (`ffmpeg`, `ffprobe` on PATH)
- podman + `localhost/hyperframes-render:latest` image for Mode B renders
  (built from HyperFrames `packages/cli/src/docker/Dockerfile.render`).
  Mounts use `:Z` relabels (REQUIRED on SELinux Bluefin).
- For `impromptu tts`: the HyperFrames CLI on PATH + python3 with
  `kokoro-onnx`/`soundfile` (e.g. inside distrobox). The stock render
  image lacks python3 so container TTS fails until the image is extended.

## Usage

```
impromptu script.md                    # teleprompter
impromptu new my-script.md             # scaffold sample script
impromptu scaffold videos/my-video/    # project layout (script.md + scene-plan.json samples)
impromptu composite plan.json -p me.mp4 -g g0.mp4 -o final.mp4
impromptu composite plan.json -p me.mp4 --graphics-track gfx.mp4 -o final.mp4
impromptu composite plan.json -p me.mp4 --normalize -o final.mp4
impromptu build-hf plan.json -p me.mp4 -o hf_project/ [--vertical]
impromptu render-hf hf_project/ -o final.mp4 [--quality draft|standard|high]
impromptu package final.mp4 --plan plan.json [--out-dir out] [--transcribe]
impromptu tts "Hello world" -o voiceover.wav [--voice af_heart]
```

Shorts: `build-hf --vertical` re-layouts to 1080x1920; for Mode A, crop the
landscape master with ffmpeg (`crop=1080:1920`). Upload is MANUAL —
`package` writes `upload-checklist.md`, never uploads.

## v2 production document

The first v2 vertical slice uses `production.yaml` as the single editable document.
It is validated with `core.document`, and `render.mlt_xml` generates named-track MLT
XML without linking libmlt. After reconciliation, `render.board.build_boards` renders
named boards through HyperFrames with `--format mov --fps N`, a one-frame duration guard,
and content-addressed caching. Starter templates cover title cards, bar charts, lower
thirds, and code reveals in landscape or vertical dimensions, using local
`/vendor/gsap.min.js`. See `docs/document-schema.md` for the normative schema.
Migrate a v1 project with `impromptu migrate <v1-dir> <out-dir>`, validate it with
`impromptu validate <dir>`, then reconcile a fixture transcript with
`impromptu reconcile <dir> --transcript-json transcript.json -t take.mp4` (or pass a
JSON-producing whisper command with `--whisper-command`). Reconciliation writes
scene-relative cues and a `drift-report.md`; the existing v1 commands remain available
during the incremental migration.

## Tests

```
python3 -m pytest tests/ -q
```

## Docs

- `docs/decisions.md` — Mode A vs B, render path, YouTube specs
- `docs/transitions.md` — 58 native xfade transitions + `none` alias
- `docs/studio.md` — Phase 4-5 server, UI, MCP, container, and verification notes
- Plan: `.hermes/plans/2026-09-05_youtube-video-pipeline-impromptu-v2.md`

### Local studio server

The optional Phase 5 web/MCP stack runs with `uv sync --extra web` followed by
`impromptu serve --videos "$HOME/workspace/videos"` (or set
`IMPROMPTU_PRODUCTIONS`). It serves `/healthz`, the production
directory/upload API, a WebSocket teleprompter, `/remote` for the phone remote,
and `/mcp` when FastMCP is installed.

Pair a phone with `impromptu pair` **while the studio is running**: the token is
minted by the server that validates it, and the printed `/remote?token=...` URL
opens the remote. Tokens are in-memory and expire after 10 minutes.

MCP exposes 12 intent-shaped tools — `read_document`, `patch_document`,
`reconcile_run`, `direct_run`, `scene_layout`, `drift_report`, `boards_build`,
`render_start`, `package_run`, plus production discovery and validation. None
of them uploads anything; `package_run` writes an upload checklist instead.

See `docs/studio.md`, and `docs/v2-traceability.md` for what is verified by real
execution versus still outstanding.

## License

MIT — Panagiotis Xynos (hi@onlyascii.io)
