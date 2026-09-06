# impromptu v2 — what's left

> **Status of the source plan** (`2026-09-06_impromptu-v2-lean.md`): every phase
> shipped. Phases 1–5 are implemented, and the two items that document listed as
> "not built" — voice-following prompter scroll and the render queue — are now
> built and verified against a live server.
>
> Nothing below blocks making a video. This is the honest backlog, ordered by
> what would bite first.

---

## 1. Ship the guard's counterpart in `reconcile`

**Why:** `render` now refuses a take shorter than its timeline
(`docs/fixed-take-shorter-than-timeline.md`), but it catches the problem one
step *after* it is created. `reconcile` writes the `measured_sec` values that
overran the recording in the first place — the demo's three scenes summed to
12.0s of take time against an 11.77s take.

**Do:** assert in `core/reconcile.py` that the durations it writes do not exceed
the take it just measured, and fail there with the same shape of message. The
render-time guard stays as the backstop, since a document can also be
hand-edited.

**Test:** a fixture transcript whose segments overrun the take must raise, and
the error must name the take and the overrun.

**Size:** small. One check, one test, reuses `render.take.presenter_frames`.

---

## 2. Decide the 4:4:4 encode option

**Why:** measured, written down, never decided. On the demo project `yuv444p`
gave RGB-SSIM 0.977 → 0.990 against a lossless reference *and* a smaller file
(725,195 vs 743,277 bytes). Saturated thin text on black — exactly what boards
are made of — is the worst case for 4:2:0, and it is the residual ~1.17 mean
error still visible on glyph edges after the alpha fix.

**Why it is not just "turn it on":** it produces `High 4:4:4 Predictive`, which
some players and platforms reject. It belongs behind an explicit flag with the
compatibility caveat in `--help`, not as a silent default.

**Do:** `impromptu render --chroma 444`, defaulting to 420. Record the
trade-off in `docs/decisions.md`.

**Size:** small. `render/melt.py` already centralises the encoder argv.

---

## 3. Verify the quadlet as a live service

**Why:** the only item still marked **blocked** in the traceability doc. The
image builds and every binary in it has been exercised directly, but
`quadlets/studio.container` has never been started as a systemd user unit —
doing so installs a unit into your live environment, which I would not do
unasked.

**Do:** you run it once (`cp quadlets/studio.container ~/.config/containers/systemd/`,
`systemctl --user daemon-reload && systemctl --user start studio.service`), and
we confirm `/healthz`, the mounted productions volume, and that the prompter and
render queue work over the published port. Then the row becomes runtime-verified.

**Size:** minutes, but needs your decision to install the unit.

---

## 4. Voice-following: two known limitations

Both are honest trade-offs in the vendored matcher, pinned by tests, not bugs.

**a. No forward leap.** The algorithm scores candidate prefixes from the last
confirmed position, so saying a phrase from the middle of the script while the
prompter sits at the top stays put. This is the right trade-off — leaping on any
fuzzy mid-script match is how other prompters lose their place on a repeated
phrase — and manual seek is the escape hatch. If it annoys you in practice, the
fix is a "resync" button that widens the search window to the whole script for
one utterance.

**b. Chrome only.** `SpeechRecognition` is a Chrome/WebKit API; Firefox does not
ship it. The UI says so and falls back to manual speed. A server-side
alternative (streaming the mic to whisper.cpp) is a much larger job and would
put an audio pipeline in the studio process — deliberately not done.

**Size:** (a) is small if wanted; (b) is a rewrite, and probably never.

---

## 5. Deferred by the source plan (still correctly not built)

Unchanged from the original plan, listed so nothing looks forgotten:

- phrase-level cueing via CTC forced alignment
- separate materialised EDL
- OTIO export for hand-finishing in Kdenlive
- in-browser MediaRecorder capture (upload only — you film on a real camera)
- multi-presenter
- TTS voiceover (v1's Kokoro path remains as `impromptu tts`)

---

## 6. Worth doing before the next real video

Not features — hygiene that the last two sessions suggest pays off.

- **Run the whole chain on a real take of yours.** Every defect found in the
  last two sessions (alpha convention, `--fps 30.0`, the `out/boards` vs
  `.cache/boards` split, the silent truncation) passed a green suite and was
  only exposed by running real tools and *looking at the pixels*. The demo take
  is a `testsrc2` pattern; a real recording will surface whatever is left.
- **Add a pixel assertion to the e2e test.** `tests/test_alpha_compositing.py`
  proves the compositor handles alpha, but the end-to-end test still asserts
  only structure. One board-region comparison against the source board would
  catch a whole class of regression.

---

## Lesson worth carrying forward

Recorded because it caused every real defect found so far, and because the
board-artifact note is a case study in getting it wrong:

**When the hypothesis is about pixel values, assert on pixel values. When it is
about durations, assert on durations.** The alpha bug was misdiagnosed for a
whole session because an isolation render was judged by eye against a resized
crop. The truncation bug hid behind a frame count that was wrong-but-plausible.
Frame counts, exit statuses and green suites all agreed while the picture was
wrong.

Also: **`httpx` missing from the dev group silently skipped every
`fastapi.testclient` test**, which is exactly why the teleprompter socket
shipped without ever sending the script. A skipped test reads like a passing
one in a summary line. Worth a periodic `pytest -q -ra` to see what is being
skipped and why.
