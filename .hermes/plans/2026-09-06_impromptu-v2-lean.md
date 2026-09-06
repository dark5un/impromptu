# impromptu v2 — plan

> **Branch:** `v2` in `~/workspace/github.com/dark5un/impromptu`
> **Engine:** MLT (decided). **Licence:** MIT (MLT via subprocess only).
> **Rule:** every phase ships something usable. You never touch a timeline or MLT XML.

---

## 1. Your flow

```
  1. brainstorm with hermes        → agent writes production.yaml (script + intent)
  2. localhost:8787 → Record       → prompter follows your voice → take saved
  3. "reconcile"                   → measured_sec per scene: what you ACTUALLY said
  4. "direct"                      → scenes cut, presenter treatment, transitions, board slots
  5. "make the boards"             → agent authors HyperFrames to the MEASURED durations
  6. skim production.yaml          → change anything you disagree with
  7. "render and package"          → master.mp4 + chapters + thumbnail + checklist
```

You never edit video. Steps 3-5 are one sentence each to the agent.

**The ordering matters.** Boards are authored *after* the recording, not before. Once
`reconcile` has run, every scene has a real measured duration — so a board is born
knowing it must be exactly 23.4s long, animating to fit the words you actually said.

That single sequencing choice removes v1's worst class of bug. v1 authored graphics
against *planned* timings, so it had to defend against graphics being shorter than their
scene (`trim=start=0:duration=dur` with no loop → freeze or early termination) and needed
a plan-validation rule requiring `graphic_duration >= scene_duration`. **In v2 that check
is unnecessary, because the duration is an input to authoring rather than a constraint
checked afterwards.**

---

## 2. The document

Replaces `script.md` + `scene-plan.json` + argv positions.

```yaml
schema: 1
title: "Why Immutable Beats Configuration Management"

target:
  orientation: landscape       # landscape | vertical — set once, constrains everything
  resolution: [1920, 1080]
  fps: 30

media:                         # named, never argv-positional
  drift-chart: {type: board, src: boards/drift.html}
  broll-racks: {type: video, src: media/racks.mp4}

presenter:
  source: takes/take-03.mp4

scenes:
  - id: the-numbers
    say: |                     # the script lives in the scene
      Here is what the drift numbers actually say.
    planned_sec: 23.0          # estimated from word count, before recording
    measured_sec: 23.4         # written by `reconcile` — what you actually said
    segments:                  # written by `reconcile`, scene-relative seconds
      - {text: "Here is what the drift numbers", start: 0.0,  end: 6.2}
      - {text: "actually say.",                  start: 6.2,  end: 8.1}
    presenter: corner          # fullscreen | corner | hidden
    overlay: drift-chart       # by name — the board authored against measured_sec
    transition: {type: wipeleft, dur: 0.4}
```

Before recording, `measured_sec` and `segments` are `null`. `reconcile` fills them, and
only then are boards authored. That's the whole loop.

Three fixes to v1's looseness: `say` lives in the scene, media has a name, and the recording
has somewhere to land.

---

## 3. Directing: what the agent can and cannot judge

Stated honestly, because the split determines where you must stay in the loop.

**The agent directs well** — these are text and timing problems, and it has the script,
the measured per-segment timings, and the media list:

- scene boundaries from the narrative structure of the script
- presenter treatment per scene (fullscreen when you're the message, corner when the board
  is, hidden for pure b-roll)
- which board or b-roll appears, when, for how long
- transition grammar — hard cut on a pivot, dissolve on a reflection, wipe on a list
- retiming everything onto what you actually said
- pacing diagnosis: "scene 4 ran 40% long, you have three consecutive 30s talking-head
  scenes, the middle third has no visual change for 90 seconds"

**The agent cannot judge** — and will not pretend to:

- whether your delivery in take 3 had more energy than take 2
- whether a frame is beautiful, or your framing/lighting is right
- whether a joke landed
- taste

**The QC pass it CAN do:** after render, extract frames at every scene boundary and every
board cue point and inspect them. That catches real defects — board overlapping the
presenter's face, text outside the safe area, PiP over the wrong shoulder, a board that
freezes because its duration was wrong, an unreadable contrast pair. It is frame
inspection, not watching. It will not catch anything that only exists in motion or in
sound.

So: **the agent is the editor and the assistant director. You remain the director of
performance.** It makes every structural and timing decision, writes them into a text file
you read in ten seconds, and you overrule anything you disagree with. That review step is
not ceremony — it is the point.

## 3.1 What "directing" means

Given the document plus your media, the agent decides and writes back into it:

- **Scene boundaries** from the narrative structure of the script
- **Presenter treatment** — fullscreen when you're the message, corner when the board is,
  hidden for pure b-roll
- **Which board or b-roll**, when, for how long
- **Transitions** matched to the beat — hard cut on a pivot, dissolve on a reflection
- **Retiming** from the recording, so everything lands on what you actually said

You review a text file. That's the judgement checkpoint — ten seconds of reading, not a
timeline UI to learn.

---

## 4. Stack

**Container = MLT + ffmpeg + whisper.cpp + HyperFrames (Node 22 + chrome-headless-shell) +
Python.** No torch, no external prebuilt images — we build one.

| Piece | Choice | Notes |
|---|---|---|
| Compositor | **MLT** — generated XML + `mlt-melt` subprocess | `dnf install mlt mlt-qt6`, in F43 main repos. Named tracks, `qtblend` PiP with keyframable `rect`, 30+ easing types, frame-exact. |
| Boards / motion graphics | **HyperFrames** — HTML+GSAP composition → ProRes 4444 alpha → MLT overlay track | §4.1. Apache-2.0, repo already cloned at `workspace/github.com/hyperframes`. Real animation, not screenshots. |
| Alignment | whisper.cpp, segment-level, matched to the known script | ±200ms is enough to retime scenes. MIT, tiny, CPU-fast. |
| Decisions | in the document — no separate EDL file | One artifact to understand. |
| Server | FastAPI + FastMCP, one process, one port | Verified on Python 3.14.6. |
| Web UI | plain ES modules, no bundler, no npm | Import maps are Baseline. |

**Licence discipline:** MLT is GPL-3.0-only AND LGPLv2+. Generate XML, shell out to
`mlt-melt`, **never link libmlt/mlt++** — impromptu stays MIT.

### 4.1 HyperFrames — boards, authored on demand

You ask, I write the board. That's the whole workflow. A board is one HTML file with a
GSAP timeline; impromptu renders it to an alpha video and MLT lays it on an overlay track.

Boards are a **post-recording** stage. By the time I author them, `reconcile` has already
written `measured_sec` for every scene, so I author against real numbers.

```
  after reconcile + direct, the document says:
      scenes[3]: measured_sec: 23.4, overlay: drift-chart

  you: "make the boards"
        ↓
  agent reads measured_sec = 23.4
        ↓
  agent writes boards/drift.html      data-duration="23.4", GSAP timeline beats
                                      placed to land inside your actual delivery
        ↓
  impromptu boards <dir>              → hyperframes render --format mov --fps 30
        ↓
  boards/drift.mov                    ProRes 4444, yuva444p10le, exactly 702 frames
        ↓
  MLT overlay track, composited by qtblend per the document
```

`media: {drift-chart: {type: board, src: boards/drift.html}}` is all the document needs.
The `.mov` is a cached build artifact, content-addressed on the HTML's hash.

**The timing contract:** `impromptu boards` refuses to render a board whose root
`data-duration` disagrees with its scene's `measured_sec` (tolerance: one frame). That
turns "the graphic doesn't fit the scene" from a silent visual glitch into a build error
with a line number. It also means re-reconciling after a new take invalidates the board
cache automatically — the duration changed, so the hash changed, so it re-renders.

**What "authoring to the measurement" actually buys:** I can place a GSAP beat on the word
you said it on. Scene 3 measured 23.4s and you hit "drift numbers" at 6.2s into it, so the
chart bars animate in at 6.2s — not at a guessed 5.0s that was wrong the moment you
breathed differently. Reconcile gives per-segment timings; the board consumes them.

**The contract I must follow when authoring** (verified against
`packages/cli/src/templates/blank/index.html` in your clone, commit `b94b5bd`):

- Root: `<div id="root" data-composition-id="main" data-start="0" data-duration="<sec>"
  data-width="1920" data-height="1080">`
- Every visible element: `class="clip"` **plus** `data-start`, `data-duration`,
  `data-track-index`. No exceptions — a missing attribute means the element won't render.
- Motion: one **paused** GSAP timeline registered as `window.__timelines["main"]`. The
  engine seeks it per frame. Miss the registration and you get a still frame.
- For a transparent board, omit the a-roll `<video>` and body background — the presenter
  comes from MLT's track below, not from inside the composition.

**Pitfall, already caught:** the stock blank template loads GSAP from
`cdn.jsdelivr.net` — that fails in an offline container. **Vendor `gsap.min.js` into the
image and template a local `<script src="/vendor/gsap.min.js">`.** Same for fonts: bake
Inter + JetBrains Mono in (`fc-cache -fv`) or your text metrics shift between builds.

**Why ProRes 4444 and not WebM alpha:** HyperFrames' `--format webm` gives VP9
`yuva420p` — the alpha plane is quarter-resolution, which fringes exactly what boards are
made of (thin strokes, small text, gridlines). `--format mov` gives ProRes 4444
`yuva444p10le`, full-resolution 10-bit alpha, and MLT composites it cleanly. Verified in
`packages/engine/src/services/chunkEncoder.ts`.

**Alpha convention — the one thing ProRes 4444 does NOT give you for free.** MLT reads a
board's colour plane as **premultiplied**; HyperFrames, being a browser compositor, writes
**straight** alpha. Nothing errors — every semi-transparent pixel simply composites at full
intensity, so `rgba(255,255,255,.10)` lands as white rather than dark grey, and
anti-aliased text edges lose their gradient (which reads as a periodic comb). Boards are
therefore premultiplied on the way into the cache:
`ffmpeg -vf premultiply=inplace=1 -c:v prores_ks -profile:v 4444 -pix_fmt yuva444p10le`.
It costs one pass per board because the `.mov` is content-addressed. Regression tests must
assert **pixel values**, not frame geometry: this defect passed frame count, duration,
resolution, CFR and SSIM-against-the-previous-render simultaneously. Full evidence in
`docs/fixed-board-alpha-convention.md`.

**Container cost, stated plainly:** HyperFrames needs Node 22 + a pinned
`chrome-headless-shell`. That's roughly +500MB on the image and a browser launch per board
render. Acceptable because boards are **cached** — they render once and the edit loop
(where you and I iterate on timing) never launches a browser. Build the render layer from
`packages/cli/src/docker/Dockerfile.render` in your clone: it already solves the arm64
SIGTRAP, pins the browser via `@puppeteer/browsers`, and wires
`PRODUCER_HEADLESS_SHELL_PATH` so BeginFrame capture is actually used. Copy that stage into
our Containerfile rather than reinventing it.

**Starter set I'll author in Phase 3:** title card, bar chart, lower third, code/terminal
reveal — each with a vertical variant. After that they're per-video, on request.

**Deferred, written down, not built:** phrase-level cueing via CTC forced alignment ·
separate materialised EDL · OTIO export for hand-finishing in Kdenlive · in-browser
MediaRecorder capture (upload only for now — you film on a real camera) · multi-presenter ·
TTS voiceover (port v1's path if you miss it).

---

## 5. Phases

### Phase 1 — document + MLT render (~3 days)
1. `docs/document-schema.md` — normative, short.
2. RED→GREEN `core/document.py`: load, validate, patch. Tests: required keys, media-name
   resolution, unknown-key rejection, scene contiguity.
3. `render/mlt_xml.py` — document → MLT XML. Seed it from the working prototype in §8
   (~90 lines, stdlib `ElementTree`).
4. `render/melt.py` — subprocess runner, `real_time=-1`, pinned threads, progress parsing.
5. `impromptu migrate` — v1 `script.md` + `scene-plan.json` → `production.yaml`, turning
   `graphic: 0` indices into media names. Test against v1's own fixtures.
6. Golden tests via `ffmpeg -f framehash` — **never** byte-compare MP4s.

**Ships: everything v1 did, from one file.**

### Phase 2 — closing the loop (~2 days)
7. `core/reconcile.py` — whisper.cpp on the take, match segments to `say` per scene. Writes
   **two** things into the document:
   - `measured_sec` per scene — what boards are authored against (Phase 3)
   - `segments: [{text, start, end}]` per scene — scene-relative segment timings, so a
     board can place a beat on the phrase you said it on
   Fixture-based tests, never real inference in CI.
8. `impromptu reconcile <dir> -t take.mp4` → updated document + drift report
   (planned vs measured per scene, so you can see where you ran long).

**Ships: the feature v1 never had — and the input Phase 3 depends on.**

### Phase 3 — boards via HyperFrames (~2 days)

Depends on Phase 2: boards are authored against `measured_sec`, so reconcile must land
first. This is why boards are Phase 3 and not Phase 1.

9. `render/board.py` — `boards/*.html` → `hyperframes render --format mov` → ProRes 4444
   alpha → registered as an MLT overlay producer. Content-addressed cache keyed on the
   HTML hash + the scene's `measured_sec`, so unchanged boards never re-render and a
   retake invalidates them automatically.
9b. Duration guard: fail the build if a board's root `data-duration` disagrees with its
   scene's `measured_sec` by more than one frame. Replaces v1's
   `graphic_duration >= scene_duration` validation entirely.
10. Vendor `gsap.min.js` locally (the stock template's CDN link fails offline) and bake
    Inter + JetBrains Mono into the image.
11. Author the starter set — title card, bar chart, lower third, code/terminal reveal —
    each with a vertical variant. Thereafter boards are authored per video, on request.

**Ships: real motion graphics, cached so the edit loop stays browser-free.**

### Phase 4 — container (~2 days)
12. `containers/Containerfile` — Fedora 43 digest-pinned, MLT 7.36.1 pinned, ffmpeg encoder
    decision explicit (§6), whisper.cpp + `ggml-base.en`, fonts baked + `fc-cache -fv`,
    plus the HyperFrames render layer (Node 22 + pinned `chrome-headless-shell` +
    `PRODUCER_HEADLESS_SHELL_PATH`) lifted from `packages/cli/src/docker/Dockerfile.render`
    in your hyperframes clone.
12. `quadlets/studio.container` — your sketchlab conventions (`ContainerName=systemd-…`,
    `Network=ai.network`, `UserNS=keep-id`, `:Z`), `%h/workspace/videos` shared with host,
    `PublishPort=127.0.0.1:8787`, `--shm-size 2G`.

**Ships: batteries-included container, nothing on the host.**

### Phase 5 — web UI + MCP (~4 days)
13. `api/http.py` — REST + upload; `web/` served from the same port.
14. Teleprompter over WebSocket: **voice-following** (it knows the script, so it scrolls as
    you speak; manual speed is an override), pause/resume, phone-as-remote via QR token.
    Fork `jlecomte/voice-activated-teleprompter` (MIT) — it exists because other prompters
    stall when you go off-script. Borrow `f/textream`'s telemetry frame schema.
15. Upload dropzone → hashed into `media:`. Render queue with progress.
16. `api/mcp.py` — FastMCP mounted in-process, ~12 hand-written intent-shaped tools
    (`doc.patch`, `reconcile.run`, `direct.run`, `render.start`, `package.run`). Not
    auto-derived from REST routes.

**Ships: the product. ~13 days total, usable at every phase boundary.**

---

## 6. MLT gotchas already hit and solved

1. **Binary is `mlt-melt`** (or `melt-7`). There is no `melt` on Fedora.
2. **`real_time=-1` on the consumer is mandatory** — default realtime scheduling drops and
   duplicates frames, making output nondeterministic.
3. **`qtblend` `rect` opacity is the 5th field, `0..1` not `0..100`.**
   `70%/68%:25%x25%:1` = opaque. `:100` renders semi-transparent.
4. **Set `compositing=1`** on the qtblend transition.
5. **Audio needs an explicit `mix` transition** or an overlay track silences your voice.
6. **Digest-pin the image.** MLT 7.36.0 changed `luma` to linear-light blending; a bump to
   F44's 7.40.0 changes your pixels.
7. **`ffmpeg-free` on F43 has NO libx264.** Available: `libopenh264`, `libvpx-vp9`,
   `prores_ks`. Add RPM Fusion ffmpeg or accept `libopenh264` (bitrate-based, no CRF).
   Decide in the Containerfile, record it in `docs/decisions.md`.
8. `dbind-WARNING … AT-SPI … dbus-daemon` on every run — harmless, ignore.
9. **`/dev/shm` is 64MB in containers** — chromium dies `BUS_ADRERR`. `--shm-size 2G`.
10. **Normalise uploads to CFR on ingest**, not at render:
    `-fps_mode cfr -r 30 -ar 48000 -movflags +faststart`, then reject if
    `avg_frame_rate != r_frame_rate`. Phone footage is VFR and desyncs downstream.

---

## 7. HOWTO

### Setup, once

> **Where this runs.** The agent works inside the `ai` distrobox; podman,
> systemd and the quadlet all live on the **host**. Prefix every podman /
> systemctl command with `distrobox-host-exec` when running it from the
> container, and remember `%h` in a quadlet is the *host* home
> (`/var/home/panos`), not the container's.

```bash
cd ~/workspace/github.com/dark5un/impromptu && \
distrobox-host-exec podman build -t localhost/impromptu:latest -f containers/Containerfile . && \
distrobox-host-exec sh -c 'mkdir -p ~/workspace/videos ~/workspace/impromptu-models' && \
distrobox-host-exec cp quadlets/studio.container ~/.config/containers/systemd/ && \
distrobox-host-exec systemctl --user daemon-reload && \
distrobox-host-exec systemctl --user start studio.service && \
curl -s http://127.0.0.1:8787/healthz
```

The final `curl` needs no prefix: the port is published on the host loopback
and distrobox shares the host network namespace.

### Making a video

```bash
# 1. brainstorm in hermes, ending with:
#      "write the production document for videos/chapter-51/"

# 2. open http://localhost:8787 → pick the production → Record
#    prompter follows your voice · space pauses · arrows nudge speed
#    phone as remote: `impromptu pair`, scan the QR

# 3. in hermes:
#      "reconcile take 3 and direct the edit"
#    → measured_sec per scene, scenes cut, presenter treatment, transitions, board slots

# 4. in hermes:
#      "now make the boards"
#    → I author boards/*.html against the MEASURED durations, then:
impromptu boards videos/chapter-51/

# 5. review videos/chapter-51/production.yaml, change what you disagree with

# 6. render:
impromptu render videos/chapter-51/ && impromptu package videos/chapter-51/
```

Output in `videos/chapter-51/out/`: `master.mp4`, `chapters.txt`, `description.md`,
`thumbnail.png`, `upload-checklist.md`. **Upload is always manual.**

### CLI

```
impromptu new <dir>                     scaffold a production
impromptu validate <dir>                check the document, fail with line numbers
impromptu migrate <v1-dir> <out-dir>    v1 files → production.yaml
impromptu reconcile <dir> -t take.mp4   whisper → measured_sec + per-segment timings
impromptu direct <dir>                  scenes, presenter treatment, transitions, board slots
impromptu boards <dir>                  render boards/*.html → cached ProRes alpha .mov
                                        (run AFTER reconcile — enforces the duration guard)
impromptu render <dir> [--vertical]     document → MLT XML → mlt-melt → final.mp4
impromptu package <dir>                 loudnorm + chapters + thumbnail + checklist
impromptu pair                          QR + token for phone-as-remote
impromptu serve                         web UI + MCP (what the container runs)
```

### Troubleshooting

| Symptom | Fix |
|---|---|
| `melt: command not found` | use `mlt-melt` |
| Frames drop / nondeterministic render | add `real_time=-1` |
| PiP is see-through | `rect` opacity is `0..1`: `…:25%x25%:1` |
| Presenter audio missing under overlay | add explicit audio `mix` transition |
| `Unknown encoder 'libx264'` | use `libopenh264` or add RPM Fusion ffmpeg |
| Pixels changed after rebuild | digest-pin image; bake fonts + `fc-cache -fv` |
| chromium `BUS_ADRERR` | `--shm-size 2G` |
| Board renders as a still frame | GSAP timeline not registered as `window.__timelines["main"]`, or not `paused: true` |
| Board element invisible | missing `class="clip"` or one of `data-start` / `data-duration` / `data-track-index` |
| Board render fails offline | GSAP still pointing at the jsdelivr CDN — use the vendored copy |
| Board edges look fringed | rendered `--format webm` (VP9 yuva420p, quarter-res alpha) — use `--format mov` |
| `board duration mismatch` build error | board authored before reconcile, or a new take changed `measured_sec` — re-author or re-run `impromptu boards` |
| Phone footage desyncs | CFR-normalise on ingest |
| `dbind-WARNING … AT-SPI` | harmless |
| Board semi-transparency renders at full opacity (white bar tracks, "comb" on text edges) | HyperFrames writes **straight** alpha, MLT reads it as **premultiplied**. Boards are premultiplied at build time (`premultiply=inplace=1`); see `docs/fixed-board-alpha-convention.md`. Fixed 2026-09-06. |
| `hyperframes: Invalid fps` | `--fps` was given as `30.0`; whole rates must serialise as `30`. Fixed in `hyperframes_command`. |
| `boards` succeeds but `render` says the board is unrendered | The two commands disagreed on a directory (`out/boards` vs `.cache/boards`). Both use the cache now. Fixed 2026-09-06. |
| Final scene ends early / output shorter than the document | The presenter take is shorter than the timeline cut from it; MLT clamps to the source and truncates silently. `render` now refuses first, naming the scene and shortfall — re-run `reconcile` against the take. See `docs/fixed-take-shorter-than-timeline.md`. Fixed 2026-09-06. |

---

## 8. Proven prototype (Phase 1 seed)

Verified on this machine 2026-09-06, `/tmp/mlttest/`: `gen.py` (~90 lines, stdlib
`ElementTree`) generates MLT XML for a 3-scene composite with picture-in-picture;
`mlt-melt` rendered it to 900 frames, exactly 30.0s, 30/1 CFR, H.264 + AAC in 7.5s.

Copy `gen.py` → `render/mlt_xml.py` as the starting point for Phase 1 step 3.
