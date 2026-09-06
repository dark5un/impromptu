# Fixed: a take shorter than its timeline was silently truncated

Status: **fixed** in `render/take.py`, 2026-09-06. Found while wiring the render
queue's progress denominator (`api/queue.py programme_frames`).

## Symptom

The document's timeline could ask for presenter frames the take did not have.
MLT clamps to the end of the source, so the render ended early with **no
warning and a zero exit status**.

Measured on the demo production:

| Quantity | Frames |
|---|---|
| Presenter take (`takes/take.mp4`) | 353 |
| Timeline's last required take frame | 360 |
| Programme length from `scene_layout` | 336 |
| Actually rendered | **329** |

The final scene lost 7 frames (~0.23s) and nothing said so.

## Why it happened

`scene_layout` cuts scenes from a *continuous* recording, advancing a take
cursor by each scene's duration (`take_cursor += duration`). Nothing checked
that the recording contained those frames. The demo's `measured_sec` values
total 12.0s of take time (4.08 + 4.40 + 3.52) against an 11.77s recording,
because reconcile measured each scene from a take that also carries leading
silence, so the cursor walked off the end.

MLT was not at fault: clamping is the only reasonable thing to do with an
in-point beyond the source.

## Why it mattered more than 7 frames

It was silent, and it scaled: a take five seconds short would lose five seconds
of the final scene, still exiting zero. The output's frame count is
wrong-but-plausible and matches neither the document nor anything else worth
diffing, so **every structural assertion in the suite passed** — the same
blind-spot class as the board alpha bug.

## The fix

`render/take.py` validates before `mlt-melt` is invoked, from
`render_production`:

- `presenter_frames()` counts frames with `ffprobe -count_frames` rather than
  trusting the container's `nb_frames` hint, which is often absent or wrong.
  Takes are minutes long at most, so the decode is cheap next to a render — and
  the check only pays off if it is accurate.
- `required_take_frames()` measures **take time, not programme time**. A
  transition overlaps two scenes' output positions, but each scene is still cut
  from its own stretch of recording; measuring the programme would wrongly pass
  a short take whenever transitions were used.
- Tolerance is one frame, matching the board duration guard, because encoders
  land a frame either side of a requested duration and a zero-tolerance check
  would reject correct documents.

`TakeTooShortError` subclasses `DocumentError` (a `ValueError`), so the render
CLI and the MCP tools report it through their existing handlers with no change.

The guard is unconditional — there is no flag to switch it off, because that is
exactly how a silent-truncation bug returns.

## Verified

The production that produced the original defect, on the host and in the
container (identical output):

```
❌ render failed: presenter take is too short for the timeline: scene 'outro'
needs take frame 360 but take.mp4 has 353 (0.23s short at 30fps). MLT would
silently truncate the final scene. Re-run `impromptu reconcile` against this
take so measured_sec matches what was actually recorded, or record a longer
take.
```

Exit status 1. Trimming the outro's `measured_sec` to 3.28s — what reconciling
against the real take would produce — renders cleanly at 328 frames.

## Regression tests

`tests/test_take_length.py`, nine tests asserting on the **error**, never on
frame counts, since the frame count is exactly what looked fine before:

- a long-enough take passes; a short one raises naming the scene, the shortfall
  in seconds, and the fix
- an exact fit passes (one-frame tolerance)
- transition overlap does not excuse a short take
- `render_production` refuses before the renderer runs (the stub runner asserts
  if reached)
- the CLI reports it and exits 1
- `TakeTooShortError` is a `DocumentError`, so existing handlers cover it

## Related, deliberately not done here

`reconcile` could assert that the measured durations it writes do not exceed
the take it just measured, catching the inconsistency where it is introduced
rather than one step later at render. Tracked in the follow-up plan.
