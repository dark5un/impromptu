# Third-Party Notices

impromptu's **own source code is MIT** (see `LICENSE`). This file records every
third-party component the project depends on, bundles, or invokes, and the
licence under which each is used. It exists so nothing is misrepresented: some
components impromptu shells out to are GPL, and GSAP is not an OSI open-source
licence at all.

---

## How to read this

impromptu is **MIT** for its own code because it only ever *invokes* external
programs as subprocesses — it never **links** against a GPL/LGPL library, never
loads a `.so`, never imports libav or libmlt. Calling a GPL program as a
separate process does **not** make your program a derivative work: linking or
copying GPL code is what would. That discipline is deliberately maintained in
`render/` (MLT XML generation + `mlt-melt` subprocess, ffmpeg subprocess) and
`core/reconcile.py` (`whisper-cli` subprocess).

**Bundled** means the component is copied into the ship or the container image.
**Invoked** means it is run as an external subprocess and is a runtime
requirement.

---

## Components

| Component | Version/ref | Licence | Used as | Source |
|---|---|---|---|---|
| **impromptu (this project)** | — | **MIT** | — | `LICENSE` |
| **speech-matcher.js** (vendored) | jlecomte/voice-activated-teleprompter + gustf/js-levenshtein | MIT | vendored, in repo | `web/static/vendor/NOTICE` |
| **whisper.cpp** | `master` at build | MIT | invoked (`whisper-cli`) | github.com/ggml-org/whisper.cpp |
| **HyperFrames** | `latest` (Apache-2.0) | Apache-2.0 | invoked (`hyperframes`) | github.com/heygen-com/hyperframes |
| **PyYAML** | `>=6` | MIT | pip dependency | pypi.org/project/PyYAML |
| **FastMCP** | `>=2` | Apache-2.0 | optional pip dependency | github.com/PrefectHQ/fastmcp |
| **FastAPI** | `>=0.115` | MIT | optional pip dependency | pypi.org/project/fastapi |
| **uvicorn** | `>=0.34` | BSD-3-Clause | optional pip dependency | pypi.org/project/uvicorn |
| **python-multipart** | `>=0.0.9` | Apache-2.0 | optional pip dependency | pypi.org/project/python-multipart |
| **MLT / `mlt-melt`** | Fedora `mlt` package | **GPL-2+ binary** (`melt` app); LGPL-2.1+ (framework lib) | **invoked** (`mlt-melt`) | mltframework.org; source via Fedora |
| **FFmpeg (RPM Fusion build)** | Fedora 44, via Containerfile | **GPL-2+** (libx264 forces GPL) | **invoked** (`ffmpeg`/`ffprobe`) | ffmpeg.org; source via RPM Fusion |
| **GSAP** | `gsap@3` (build-time) | **GreenSock Standard "No-Charge" — NOT an OSI licence** | **bundled** minified into the container image | gsap.com/standard-license |

---

## The GPL boundary (MLT and ffmpeg)

`mlt-melt` (the `melt` application) is **GPL-2+**, and the RPM Fusion ffmpeg
build that enables libx264 is **GPL-2+**. impromptu does **not** link either:

- It writes an MLT **XML** file and runs `mlt-melt` as a subprocess.
- It runs `ffmpeg`/`ffprobe` as subprocesses.

Under GPL, distributing those *unchanged upstream binaries* is permitted —
their source is offered upstream by Fedora (for `mlt`) and RPM Fusion / x264
project (for ffmpeg/libx264). impromptu neither modifies nor distributes their
source as its own. If you redistribute the container image, those GPL binaries
are present inside it, and the standard GPL obligations (offer of
corresponding source) are satisfied by the upstream Fedora/RPM Fusion source
packages. impromptu's own MIT code is not a derivative of them.

---

## GSAP — read this carefully

GSAP is **not** MIT, Apache, GPL, or any OSI open-source licence. Since Webflow
acquired GreenSock (2024–2025) it is free for **commercial use** under the
GreenSock **Standard "No-Charge" License**, but it is still proprietary and
comes with conditions:

- You may use, reproduce, and implement it for "Permitted Uses" — broadly, any
  website/application where it is not being used to build a *Webflow-compatible*
  no-code visual-animation builder.
- You may **not** reverse-engineer it to build a competitive visual animation
  tool, and must not remove its branding/notices.
- It can be terminated for non-compliance.

impromptu vendors a minified copy into the container image so boards render with
real animation offline (the stock HyperFrames blank template's CDN link fails
in an offline container). This is a **Permitted Use**: boards are authored as
HTML/code and rendered, not offered as a no-code visual-animation builder, and
impromptu does not compete with Webflow. The full licence text is at
https://gsap.com/standard-license.

The minified file carries GSAP's own licence header; do not strip it.

---

## Vendored code already documented

The MIT-licensed `web/static/vendor/speech-matcher.js` has its own detailed
attribution in `web/static/vendor/NOTICE`; this file does not repeat it.

---

## Licence summary for the README

- **impromptu's code** — MIT (Panagiotis Xynos, hi@onlyascii.io).
- **Bundled/invoked components carry their own licences** as listed above;
  notably **GPL-2+** (MLT `mlt-melt`, ffmpeg/libx264) and **GreenSock
  Standard No-Charge** (GSAP), which is not an opensource licence.