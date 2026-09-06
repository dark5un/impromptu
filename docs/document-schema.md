# Production document schema

`production.yaml` is the single editable artifact for an impromptu v2 production.
The schema is intentionally small and rejects unknown keys so agent-authored edits
fail loudly rather than being silently ignored.

```yaml
schema: 1
title: Why Immutable Beats Configuration Management
target:
  orientation: landscape       # landscape or vertical
  resolution: [1920, 1080]     # must match orientation
  fps: 30
media:
  drift-chart: {type: board, src: boards/drift.mov}
presenter:
  source: takes/take-03.mp4
scenes:
  - id: the-numbers
    say: |
      Here is what the drift numbers actually say.
    planned_sec: 23.0
    measured_sec: null          # filled by reconcile
    segments: null              # [{text, start, end}], scene-relative
    presenter: corner           # fullscreen, corner, hidden
    overlay: drift-chart         # named media entry or null
    transition: {type: dissolve, dur: 0.4}
```

Scene timing is contiguous in document order. Before recording, `measured_sec` and
`segments` are null. Reconciliation writes the measured duration and segment cues;
boards are authored only after that point. `render/mlt_xml.py` consumes measured
values when present and planned values otherwise.

The Python API is:

- `core.document.load_document(path)` — parse and validate YAML.
- `core.document.validate_document(value)` — return line-oriented error strings.
- `core.document.patch_document(path, {"title": "..."})` — validate, patch, and write.
- `render.mlt_xml.write_mlt(document, destination, root)` — generate XML without linking
  against MLT.
- `render.melt.run_melt(project, output)` — invoke `mlt-melt` with `real_time=-1`.

MLT remains an external subprocess under the MIT licence boundary.

## Phase status

The document core and deterministic MLT generator are implemented and covered by tests.
The CLI migration, reconciliation, boards, container, service, and UI are subsequent
implementation phases from the v2 plan.

## Compatibility note

The existing v1 JSON/ffmpeg and HyperFrames commands remain available while the v2
YAML path is introduced incrementally.

## License

MIT — Panagiotis Xynos (hi@onlyascii.io)

## Decisions

- MLT is invoked through `mlt-melt`; impromptu does not link libmlt.
- Compositing uses named playlists and an explicit `mix` transition for audio.
- The render consumer receives `real_time=-1` to avoid realtime frame dropping.
- `mlt-melt` output codec/container configuration remains a deployment concern until
  the container phase pins Fedora/MLT/ffmpeg versions.

## Local development

```bash
python3 -m pytest tests/ -q
```

The repository currently keeps runtime dependencies minimal; the YAML document layer
uses the already-installed PyYAML package and will be declared in the container/project
metadata during the container phase.

## Next phases

The remaining phases implement `migrate`, fixture-driven Whisper reconciliation, board
rendering with a one-frame duration guard, the Fedora container/quadlet, and the local
FastAPI/FastMCP studio server described in the plan.

## Source plan

`.hermes/plans/2026-09-06_impromptu-v2-lean.md`

## Status

This file tracks the first shipped vertical slice, not a promise that all plan phases
are already complete.

## Notes

The document model deliberately keeps decisions in one file: no separate EDL is
introduced by this phase.

## Review

After reconciliation and directing, the user reviews the YAML before rendering.

## Validation

Unknown top-level, nested, media, and scene keys are rejected. Media references must
resolve by name. Orientation and resolution are coupled.

## Timing

Planned seconds provide a deterministic pre-recording fallback. Measured seconds are
the authoritative post-recording value.

## Scope

This schema does not attempt to judge delivery energy, taste, framing, lighting, or
whether a joke landed; those remain director decisions.

## End

The implementation is intentionally incremental so each phase can be tested and used.
