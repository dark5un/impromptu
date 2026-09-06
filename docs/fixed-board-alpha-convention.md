# Fixed: board alpha convention (was "comb/picket artifact")

Status: **fixed** in `render/board.py`, 2026-09-06. Reported by Panos from the
demo master. Kept rather than deleted because the *first* diagnosis in this file
was wrong, and how it was wrong is the useful part.

## Symptom

In the rendered master, board scenes showed a vertical comb/picket pattern
around the title and along the bars, and the bar *track* rendered **pure white**
where the source board had `rgba(255,255,255,.10)` (dark grey).

## Root cause

**HyperFrames writes straight (non-premultiplied) alpha; MLT consumes the colour
plane as if it were already premultiplied.** MLT therefore never scales the
board's colour by the board's own alpha, so a 10%-opaque white pixel composited
at full white instead of `255 * 0.10 = 26`.

The comb was a *consequence*, not a separate defect: once every semi-transparent
pixel is pushed to full intensity, anti-aliased glyph edges and hairline rules
lose their gradient and alternate hard between extremes.

## Why the first diagnosis was wrong, and the lesson

This file originally named **interpolated `affine` `rect` keyframes** as the
prime suspect, having "ruled out" chroma subsampling, HyperFrames, the encoder,
and static-rect `affine`. That conclusion was wrong, and the error is
instructive: the isolation test that "cleared" `affine` used a *static rect*,
and its output was compared **by eye against a resized crop**, not against
computed pixel values. The static-rect render was equally broken; nobody
measured it.

The decisive test was cheaper than any of the ones already run:

```
render the board through a BARE producer — one track, no transition,
no keyframes, no compositing at all — and read the pixel value.
```

It still came out 255. That single number eliminated compositing, keyframes and
`affine` in one step, because none of them were in the graph.

**Lesson: when a hypothesis is about pixel values, assert on pixel values.**
Every wrong turn here came from comparing images visually instead of numerically.

## Evidence

The bar-track pixel authored `rgba(255,255,255,26/255)`, expected `26` over black:

| Configuration | Result |
|---|---|
| Source ProRes board, alpha applied in numpy | 26 (reference) |
| Bare MLT producer, no compositing | **255** |
| `affine` over black, static rect | **255** |
| `affine` over black, keyframed rect | **255** |
| `mlt_image_format` = `rgba` / `rgba24a` / `rgb24a` | **255** |
| `skip_alpha=0` on the producer | **255** |
| Re-encoded to `yuva444p10le`, `-alpha_bits 16` | **255** |
| Re-encoded to qtrle ARGB | **255** |
| **After `premultiply=inplace=1`** | **25** ✓ |

Whole-frame error in the board region, against the source board composited over
black:

| Render | mean abs error | bar track pixel |
|---|---|---|
| Old demo master | 39.318 | `[255,255,255]` |
| Fixed, host MLT 7.36.1 | 1.183 | `[25,25,25]` |
| Fixed, container MLT 7.40.0 + libx264 | 1.167 | `[25,25,25]` |

## The fix

`render/board.py` premultiplies each board after HyperFrames renders it and
before it lands in the content-addressed cache:

```
ffmpeg -i <straight>.mov -vf premultiply=inplace=1 \
       -c:v prores_ks -profile:v 4444 -pix_fmt yuva444p10le -an <cache>.mov
```

It runs at **board-build** time, not render time, because the `.mov` is a cached
artifact: one conversion per board, and the edit loop pays nothing. MLT ships no
premultiply filter (`mlt-melt -query filters`), so an ffmpeg pass is the only
option. The straight-alpha intermediate is deleted after conversion.

## Regression tests

`tests/test_alpha_compositing.py`, pixel-truth by construction, since every
structural assertion (329 frames, 10.986s, 1920x1080, CFR 30, SSIM against the
previous render) passed while the picture was wrong:

- a 10%-opaque board pixel must composite to ~26, not 255
- opaque pixels must be **unchanged** by premultiplying
- the conversion must preserve frame count, dimensions, rate and the alpha plane
- straight alpha must **still** be wrong — so if MLT ever changes convention, the
  now-redundant premultiply fails loudly instead of silently double-multiplying

They skip without ffmpeg/mlt-melt and run for real in the container.

## Residual, and it is not this bug

About 1.17 mean error remains, confined to anti-aliased glyph edges. It is
**chroma subsampling**, confirmed by rendering the same project losslessly
(ffv1, mean 1.092 — essentially identical), so it is not introduced by H.264.

`yuv444p` measured better on the earlier audit (RGB-SSIM 0.977 → 0.990, smaller
output) but produces `High 4:4:4 Predictive`, which some players and platforms
reject. It belongs behind an explicit option, not as a silent default, and is
tracked separately from this bug.
