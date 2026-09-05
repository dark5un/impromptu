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
