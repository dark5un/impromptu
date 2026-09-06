# Open bug: comb/picket artifact on composited boards

Status: **diagnosed, not fixed.** Reported 2026-09-06 by Panos from the demo
master. Everything below is evidence gathered in this environment, not
inference.

## Symptom

In the rendered master, board scenes show a regular **vertical comb/picket
pattern**: dotted stripes above and below the title text, hard vertical ribs
along the coloured portion of each bar. Two secondary tells:

- The bar *track* renders **pure white** in the master but is
  `rgba(255,255,255,.10)` (dark grey) in the source board.
- The green title text looks desaturated and softer than the source.

The pattern is *periodic and hard-edged*. That matters diagnostically: lossy
encoders produce soft, blocky mush, never clean combs. Periodic structure means
a scaling/geometry/resample fault, not compression.

## What has been ruled out, with evidence

Each stage was rendered and the same crop region inspected.

| Suspect | Verdict | Evidence |
|---|---|---|
| Chroma subsampling (4:2:0) | **not the cause** | First hypothesis, and wrong. 4:4:4 does measure better in RGB space (RGB-SSIM 0.977 → 0.990, and slightly smaller), but it does not remove the comb. Worth doing separately; not this bug. |
| HyperFrames / the board itself | **innocent** | The pristine `.mov` composited over black outside MLT is perfectly clean: solid text, solid bar, correct dark-grey track. |
| The H.264 encoder | **innocent** | The comb is present in a **lossless ffv1** render of the same project. |
| MLT `affine` as such | **innocent** | An isolation project — same board, same `affine`, but ONE static `rect` — renders clean, including the correct dark-grey track. |

## Prime suspect: interpolated `rect` keyframes

The isolation test that came out clean used a single static rect. The real
project's composite carries keyframed geometry (`render/mlt_xml.py`, the
`has_bed` branch of `document_to_xml`):

```
rect = 0|=0%/0%:100%x100%:100%;110|=70%/68%:25%x25%:100%;230|=0%/0%:100%x100%:100%
```

The hypothesis is that `affine` **interpolates between these keyframes**,
continuously scaling the 1920x1080 board through fractional sizes frame by
frame instead of snapping at scene boundaries. Resampling a graphic with thin
strokes and hairline rules to fractional dimensions produces exactly this class
of periodic artifact, and interpolated scaling with an alpha plane also
explains the track turning white.

Note the intent was always discrete: the presenter should be fullscreen, then
inset, then fullscreen — never smoothly zooming.

## How to confirm (one step)

Render the real project twice, changing only the keyframe syntax, and compare
the same frame:

1. As-is (`|=`).
2. With discrete/step keyframes so no interpolation occurs.

If the comb disappears in (2), confirmed. Check `mlt-melt -query
"transition=affine"` for the exact step-keyframe token before guessing — MLT's
animation syntax distinguishes `=` (linear), `|=` (discrete/step) and `~=`
(smooth), and the current code already uses `|=`, so **verify what `|=`
actually does in 7.40 rather than assuming it is discrete.** If `|=` is already
discrete, the next suspect is `fill=1` forcing a rescale even at 100%; test
`fill=0`, then a per-scene composite instead of one keyframed transition.

## Reproduce

```bash
# the exact demo production, already reconciled and directed
cd /tmp/e2e/videos/chapter-e2e        # if still present; else re-run the e2e steps
python3 impromptu.py render . --threads 4

# pristine board for comparison (should be clean)
ffmpeg -i .cache/boards/drift-*.mov -vf "select=eq(n\,58)" -vframes 1 /tmp/board.png

# the artifact, in the master
ffmpeg -i out/master.mp4 -vf "select=eq(n\,190),crop=1280:340:96:110" -vframes 1 /tmp/master.png
```

Compare `/tmp/board.png` against `/tmp/master.png`. Inspect **pixels**, not
frame counts: every structural assertion (329 frames, 10.986s, 1920x1080, CFR
30, SSIM against the previous render) passes with the artifact present. This
bug is invisible to the entire existing test suite.

## Regression test to add with the fix

A test that renders a board with a hairline rule over a presenter and asserts
the composited row matches the source row within a tolerance — i.e. compares
pixels, not geometry metadata. Without that, this defect can silently return.

## Related work worth doing separately

`yuv444p` instead of `yuv420p` for the final encode. Measured on this project
against a lossless 4:4:4 reference: RGB-SSIM 0.977162 → 0.989561, output
725,195 bytes vs 743,277. Better on the metric that matches the eye, and
smaller. The caveat is compatibility: it produces `High 4:4:4 Predictive`,
which some players and platforms reject, so it should be a documented option
rather than the silent default. Saturated thin text on black — exactly what
boards are made of — is the worst case for 4:2:0.
