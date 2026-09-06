# Open bug: a take shorter than its timeline is silently truncated

Status: **open, diagnosed, not fixed.** Found 2026-09-06 while wiring the
render queue's progress denominator (`api/queue.py programme_frames`).

## Symptom

The document's timeline can ask for presenter frames the take does not have.
MLT clamps to the end of the source and the render simply ends early, with no
warning and a zero exit status.

Measured on the demo production:

| Quantity | Frames |
|---|---|
| Presenter take (`takes/take.mp4`) | 353 |
| Timeline's last required in-point (`out="359"`) | 360 |
| Programme length from `scene_layout` | 336 |
| Actually rendered | **329** |

So the final scene loses 7 frames (~0.23s) off its end, and nothing says so.

## Why it happens

`scene_layout` lays scenes end to end against a *continuous* take:
`take_cursor += duration` per scene. The demo's `measured_sec` values total
12.0s of take time (4.08 + 4.40 + 3.52) while the recording is 11.77s. Because
reconcile measured each scene from the take and the take also carries leading
silence, the cursor walks past the end of the source.

This is not the alpha bug and not a compositor fault: MLT is doing the only
reasonable thing with an in-point beyond the source.

## Why it matters more than 7 frames

It is silent. The failure mode scales with the mismatch: a take that is 5s
short of its document loses 5s of the final scene, still with a successful
exit. `nb_frames` on the output is *also* wrong-but-plausible, so the existing
structural assertions cannot catch it — this is the same class of blind spot as
the alpha bug.

## The fix, when it is done

Validate at render time, before invoking mlt-melt: probe the presenter source's
frame count and refuse (or explicitly report) when
`max(take_start + duration) * fps` exceeds it. The error should name the scene,
the shortfall in seconds, and point at re-running `reconcile` against the
correct take.

Worth considering alongside it: `reconcile` could assert that the sum of the
measured durations does not exceed the take it just measured, which would catch
the inconsistency at the point it is introduced rather than at render.

## Regression test to add with the fix

Build a document whose scenes require more frames than a short fixture take
provides, and assert the render raises with the scene named. Assert on the
*error*, not on the frame count, since the frame count is exactly what looks
fine today.
