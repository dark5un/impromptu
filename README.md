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
         impromptu package final.mp4 --> loudnorm master + chapters + thumbnail + description (+ Shorts + TTS)
```

## Modes

- **Mode A (keep, fix):** per-scene HyperFrames renders, stitched with ffmpeg
  (fixed chained-xfade offsets, plan validation, CFR output). Best for quick
  turnaround and ffmpeg-only effects (chromakey).
- **Mode B (default):** one `index.html` (presenter a-roll + overlay clips,
  one paused GSAP timeline) rendered ONCE via the one-shot
  `localhost/hyperframes-render:latest` container. No per-scene MP4s, no
  xfade chain.

## Requirements

- Python 3 (stdlib only, no dependencies)
- FFmpeg 7+ with ffprobe (`ffmpeg`, `ffprobe` on PATH)
- podman + `localhost/hyperframes-render:latest` image for Mode B renders
  (built from HyperFrames `packages/cli/src/docker/Dockerfile.render`;
  mount project at `/project:ro`, output dir at `/output`)

## Usage

```
impromptu script.md                    # teleprompter
impromptu new my-script.md             # scaffold sample script
impromptu scaffold videos/my-video/    # project layout (script.md + scene-plan.json samples)
impromptu composite plan.json -p me.mp4 -g g0.mp4 -o final.mp4
impromptu composite plan.json -p me.mp4 --graphics-track gfx.mp4 -o final.mp4
impromptu build-hf plan.json -p me.mp4 -o hf_project/
impromptu render-hf hf_project/ -o final.mp4
impromptu package final.mp4 --plan plan.json [--shorts] [--tts]
```

## Tests

```
python3 -m pytest tests/ -q
```

## Docs

- `docs/decisions.md` — Mode A vs B, render path, YouTube specs
- `docs/transitions.md` — 58 native xfade transitions + `none` alias
- Plan: `.hermes/plans/2026-09-05_youtube-video-pipeline-impromptu-v2.md`

## License

MIT — Panagiotis Xynos (hi@onlyascii.io)
