# Decisions (locked 2026-09-05, Panos)

## Repo

`~/workspace/github.com/dark5un/impromptu` — new standalone repo, NOT
ai-lab-quadlets. Python 3 stdlib-only (no uv, no deps) so the CLI runs
everywhere FFmpeg exists.

## Mode A vs Mode B

- **Mode B default:** `impromptu build-hf` generates ONE HyperFrames project
  (`index.html` with presenter a-roll + overlay clips + one paused GSAP
  timeline), then ONE render. Kills N-render + ffmpeg-stitch complexity.
- **Mode A fallback:** per-scene HF renders + ffmpeg composite (fixed xfade,
  validation, CFR). Kept for quick turnaround and ffmpeg-only effects
  (chromakey, geq PiP).

## Render path

One-shot podman container built from HyperFrames
`packages/cli/src/docker/Dockerfile.render`, tagged
`localhost/hyperframes-render:latest`:

```
podman run --rm -v <project>:/project:ro -v <outdir>:/output <tag> \
  /project --output /output/<file>.mp4 --fps 30 --quality standard --format mp4
```

- Host has no Node, so `npx hyperframes` is NOT assumed on PATH.
- The live `127.0.0.1:3006` service is a distributed-render primitive
  (Action plan/renderChunk/assemble + GCS + Cloud Workflows), NOT a
  "POST HTML, get MP4" endpoint — do not depend on it for v0.3.

## YouTube specs (v0.3 scope)

- Landscape 1080p (1920x1080, 30fps) + camera presenter + manual upload.
- 9:16 Shorts variant (1080x1920) INCLUDED in v0.3.
- TTS voiceover (local Kokoro via `hyperframes tts`) INCLUDED in v0.3.
- Audio master: `loudnorm=I=-14:TP=-1.5:LRA=11`.
- Thumbnail 1280x720. Chapters + description from scene timings.
- NEVER auto-upload; output an upload checklist instead.

## Transition list

58 native xfade transitions (indices 0-57, verified via
`ffmpeg -h filter=xfade`) + `none` alias (0.01s fade = instant cut).
Old "64 transitions" count was wrong.

## v2 compositor: affine, not qtblend (verified 2026-09-06)

The v2 plan specified `qtblend` for compositing and documented its `rect`
opacity as "the 5th field, `0..1` not `0..100`". Both claims are wrong on
MLT 7.36.1 (Fedora 43) and were corrected against real renders.

**Service.** With a ProRes 4444 `yuva444p10le` board over a video presenter,
`qtblend` renders one or the other but never both: `compositing=0` drops the
lower track, `compositing=1` (QPainter DestinationOver) drops the board's
alpha. `affine` composites the alpha correctly. Verified by extracting frames
and inspecting them, not by frame counts — the render *succeeded* in every
case, so only pixels distinguish the two.

**Opacity.** `affine`'s `rect` is `X/Y:WxH[:opacity]` with opacity defaulting
to `100%` (per `mlt-melt -query "transition=affine"`). It is a percentage:
`:100%` is opaque and `:1` is *also* effectively solid, not 1%. The plan's
`0..1` guidance would have produced a near-invisible inset.

**Two overlay tracks.** Presenter treatment determines z-order, and one track
cannot express both cases:

- `corner` / `hidden` → board is the BED (track below); the presenter insets
  into it via a keyframed PiP rect, or is hidden entirely for pure b-roll.
- `fullscreen` → board is a TOP overlay (lower third, badge) composited over
  the presenter.

With a single track, a fullscreen presenter covered its own board and the
graphic was invisible in the output.

**Transitions.** Scenes alternate across two presenter playlists (`presenter-a`
/ `presenter-b`) so consecutive scenes can overlap; a `luma` transition spans
each overlap. `luma` with no `resource` is a cross-dissolve; a wipe needs a
grayscale PGM map. Fedora's `mlt` package ships **no** luma maps (Kdenlive's
live inside a flatpak), so impromptu generates the gradient with the stdlib and
caches it under `.cache/lumas/`. An explicit `mix` transition sums audio across
the overlap, or the incoming track silences the outgoing voice.

**Programme length.** Transitions shorten the output: N scenes with total
duration D and overlaps O render to D - sum(O). Verified: 3x4s scenes with a
0.5s dissolve and a 0.4s wipe produced exactly 333 frames / 11.114s at 30fps.

## Reconcile anchors scenes at first speech (2026-09-06)

A scene's `measured_sec` is measured from its own first word, not from the
previous scene's end, so leading silence and inter-scene pauses are not billed
as scene time. Segments therefore always start at 0.0 and the last ends exactly
at `measured_sec`.

This was a correctness bug, not a preference: the previous behaviour emitted
`segments[0].start = 1.5` for a take with 1.5s of leading silence, which
`validate_document`'s contiguity rule rejects. `reconcile` wrote documents that
`load_document` then refused to read. Gaps *inside* a scene are preserved by
extending the previous segment to the next one's start.

## `direct` fills only null fields (2026-09-06)

`direct` never overwrites a decided `presenter` or `transition`; it fills only
fields left `null`. The plan's review step — "skim production.yaml, change
anything you disagree with" — is only meaningful if your edits survive the next
`direct` run. `impromptu direct --force` re-decides every scene when you
actually want the agent's opinion back.
