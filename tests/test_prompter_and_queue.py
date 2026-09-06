"""Voice-following teleprompter and render-queue contracts (plan items 14, 15).

Both features were listed as "not built" in docs/v2-traceability.md. These
tests define what "built" means before the implementation exists.

The teleprompter tests use FastAPI's TestClient websocket support, so they
exercise the real socket rather than a mock.
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]

fastapi_testclient = pytest.importorskip(
    "fastapi.testclient", reason="requires the optional web extra"
)


def _client(tmp_path, **kwargs):
    http = importlib.import_module("api.http")
    app = http.create_app(tmp_path, **kwargs)
    return fastapi_testclient.TestClient(app)


def _production(tmp_path, name: str = "chapter-1", scenes: str | None = None) -> Path:
    """Create a minimal valid production with a two-scene script."""
    directory = tmp_path / name
    for child in ("media", "takes", "out"):
        (directory / child).mkdir(parents=True, exist_ok=True)
    body = scenes or (
        "scenes:\n"
        "- id: hook\n"
        "  say: Immutable infrastructure changes everything.\n"
        "  planned_sec: 4.0\n"
        "  measured_sec: null\n"
        "  segments: null\n"
        "  presenter: null\n"
        "  overlay: null\n"
        "  transition: null\n"
        "- id: outro\n"
        "  say: So stop patching servers.\n"
        "  planned_sec: 3.5\n"
        "  measured_sec: null\n"
        "  segments: null\n"
        "  presenter: null\n"
        "  overlay: null\n"
        "  transition: null\n"
    )
    (directory / "production.yaml").write_text(
        "schema: 1\n"
        "title: Test\n"
        "target: {orientation: landscape, resolution: [1920, 1080], fps: 30}\n"
        "media: {}\n"
        "presenter: {source: takes/take.mp4}\n" + body
    )
    return directory


# ── the script has to reach the browser at all ────────────────────────────────

def test_prompter_socket_sends_the_script_on_connect(tmp_path):
    """Voice-following is impossible if the client never receives the words.

    Regression: the socket sent only {paused, position, speed} and no text, so
    the browser had nothing to match speech against and the web prompter showed
    a placeholder string.
    """
    _production(tmp_path)
    with _client(tmp_path) as client, client.websocket_connect("/ws/teleprompter/chapter-1") as socket:
        ready = socket.receive_json()

    assert ready["type"] == "ready"
    assert "script" in ready, "the prompter must receive the script to follow"
    assert "Immutable infrastructure changes everything." in ready["script"]
    # Scene boundaries must survive, so the UI can show where a scene ends.
    assert [scene["id"] for scene in ready["scenes"]] == ["hook", "outro"]


def test_prompter_socket_reports_a_missing_production(tmp_path):
    """An unknown production must fail loudly, not serve an empty script."""
    with _client(tmp_path) as client, client.websocket_connect("/ws/teleprompter/nope") as socket:
        message = socket.receive_json()
    assert message["type"] == "error"
    assert "nope" in message["detail"]


# ── voice-following, with manual speed as the override ────────────────────────

def test_voice_position_is_accepted_and_echoed(tmp_path):
    """The browser owns recognition; the server tracks the matched position.

    Speech recognition is a browser API (and the plan's fork is a browser app),
    so the matching happens client-side and the socket carries the result. That
    keeps the server free of an audio pipeline it does not need.
    """
    _production(tmp_path)
    with _client(tmp_path) as client, client.websocket_connect("/ws/teleprompter/chapter-1") as socket:
        socket.receive_json()
        socket.send_json({"action": "voice", "position": 7})
        state = socket.receive_json()

    assert state["position"] == 7
    assert state["following"] is True, "a voice update means we are following"


def test_manual_speed_overrides_voice_following(tmp_path):
    """Plan item 14: "manual speed is an override".

    Nudging speed must take the prompter out of voice-following, otherwise the
    next recognition result would immediately fight the manual adjustment.
    """
    _production(tmp_path)
    with _client(tmp_path) as client, client.websocket_connect("/ws/teleprompter/chapter-1") as socket:
        socket.receive_json()
        socket.send_json({"action": "voice", "position": 5})
        assert socket.receive_json()["following"] is True

        socket.send_json({"action": "speed", "speed": 2.4})
        state = socket.receive_json()

    assert state["speed"] == pytest.approx(2.4)
    assert state["following"] is False, "manual speed must override following"


def test_following_can_be_resumed_after_a_manual_override(tmp_path):
    """The override must be escapable without reconnecting."""
    _production(tmp_path)
    with _client(tmp_path) as client, client.websocket_connect("/ws/teleprompter/chapter-1") as socket:
        socket.receive_json()
        socket.send_json({"action": "speed", "speed": 3.0})
        assert socket.receive_json()["following"] is False

        socket.send_json({"action": "follow"})
        state = socket.receive_json()

    assert state["following"] is True


def test_manual_seek_also_drops_following(tmp_path):
    """Seeking by hand is an override for the same reason speed is."""
    _production(tmp_path)
    with _client(tmp_path) as client, client.websocket_connect("/ws/teleprompter/chapter-1") as socket:
        socket.receive_json()
        socket.send_json({"action": "voice", "position": 9})
        assert socket.receive_json()["following"] is True

        socket.send_json({"action": "seek", "position": 2})
        state = socket.receive_json()

    assert state["position"] == 2
    assert state["following"] is False


# ── the web UI must actually wire the matcher up ──────────────────────────────

def test_web_prompter_uses_the_vendored_matcher_and_speech_api():
    js = (ROOT / "web/static/app.js").read_text()
    assert "speech-matcher.js" in js, "the UI must import the vendored matcher"
    assert "computeSpeechRecognitionTokenIndex" in js
    # Recognition must be continuous with interim results, or the position
    # only updates when the speaker pauses.
    assert "SpeechRecognition" in js
    assert "continuous" in js and "interimResults" in js


def test_vendored_matcher_is_attributed():
    """MIT code carries its notice; impromptu stays MIT and says where it came from."""
    notice = (ROOT / "web/static/vendor/NOTICE").read_text()
    assert "jlecomte/voice-activated-teleprompter" in notice
    assert "MIT" in notice
    assert "js-levenshtein" in notice
    matcher = (ROOT / "web/static/vendor/speech-matcher.js").read_text()
    assert "jlecomte" in matcher


# ── render queue with progress (plan item 15) ────────────────────────────────

def test_render_queue_reports_queued_then_progress_then_done(tmp_path):
    """`render/melt.py` already parses progress; a queue must surface it.

    Regression context: progress parsing existed but nothing exposed it, so the
    UI could only block on an opaque render.
    """
    queue_module = importlib.import_module("api.queue")
    jobs = queue_module.RenderQueue()

    observed: list[tuple[str, float]] = []

    def fake_render(directory, *, threads=1, on_progress=None):
        if on_progress:
            on_progress(50.0)
            on_progress(100.0)
        return Path(directory) / "out" / "master.mp4"

    job_id = jobs.submit(tmp_path / "chapter-1", runner=fake_render, total_frames=100)
    jobs.wait(job_id, timeout=10)
    job = jobs.get(job_id)

    assert job["state"] == "done"
    assert job["percent"] == pytest.approx(100.0)
    assert job["output"].endswith("master.mp4")
    assert observed == []  # nothing required of the caller


def test_render_queue_records_failure_with_the_reason(tmp_path):
    """A failed render must be inspectable, not silently absent."""
    queue_module = importlib.import_module("api.queue")
    jobs = queue_module.RenderQueue()

    def boom(directory, *, threads=1, on_progress=None):
        raise RuntimeError("mlt-melt exploded")

    job_id = jobs.submit(tmp_path / "chapter-1", runner=boom)
    jobs.wait(job_id, timeout=10)
    job = jobs.get(job_id)

    assert job["state"] == "failed"
    assert "mlt-melt exploded" in job["error"]


def test_render_queue_runs_one_job_at_a_time(tmp_path):
    """Concurrent mlt-melt runs would fight over CPU and thread pinning."""
    import threading

    queue_module = importlib.import_module("api.queue")
    jobs = queue_module.RenderQueue()

    concurrent = []
    running = threading.Semaphore(0)
    release = threading.Event()

    def slow(directory, *, threads=1, on_progress=None):
        concurrent.append(1)
        running.release()
        release.wait(timeout=5)
        concurrent.pop()
        return Path(directory) / "out" / "master.mp4"

    first = jobs.submit(tmp_path / "a", runner=slow)
    second = jobs.submit(tmp_path / "b", runner=slow)
    running.acquire(timeout=5)
    assert len(concurrent) == 1, "renders must be serialised"
    assert jobs.get(second)["state"] == "queued"
    release.set()
    jobs.wait(first, timeout=10)
    jobs.wait(second, timeout=10)
    assert jobs.get(second)["state"] == "done"


def test_render_api_exposes_the_queue(tmp_path):
    """The REST surface must let the UI start a render and poll it."""
    _production(tmp_path)
    with _client(tmp_path) as client:
        started = client.post(
            "/api/productions/chapter-1/render",
            json={"threads": 1},
        )
        assert started.status_code == 202, started.text
        job_id = started.json()["job_id"]

        # Without a frame total, percent stays 0 for the whole render and the
        # UI shows a stuck bar. Observed live before this was wired up.
        #
        # 213, not 225: the two scenes are 4.0s + 3.5s = 7.5s (225 frames) but
        # `direct` gives the second scene a dissolve, and the overlap is not
        # rendered twice. The total therefore has to come from the compositor's
        # own scene_layout, which is why programme_frames reuses it rather than
        # summing durations.
        queued = client.get(f"/api/renders/{job_id}").json()
        assert queued["total_frames"] == 213, (
            "the frame total must account for transition overlap, not just "
            "sum scene durations"
        )

        listed = client.get("/api/renders")
        assert listed.status_code == 200
        assert any(job["job_id"] == job_id for job in listed.json())

        polled = client.get(f"/api/renders/{job_id}")
        assert polled.status_code == 200
        assert polled.json()["job_id"] == job_id
        assert polled.json()["state"] in {"queued", "running", "done", "failed"}


def test_render_api_rejects_an_unknown_production_and_job(tmp_path):
    with _client(tmp_path) as client:
        assert client.post("/api/productions/ghost/render").status_code == 404
        assert client.get("/api/renders/not-a-job").status_code == 404
        # Path traversal must be refused by the same guard as everywhere else.
        assert client.post("/api/productions/..%2Fetc/render").status_code in {400, 404}
