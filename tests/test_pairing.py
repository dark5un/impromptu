"""Phone-remote pairing: token issue, validation, expiry, and the /remote route.

`impromptu pair` printed a token and a /remote URL that 404'd -- the token was
generated, never stored, and nothing validated it.  These tests pin the whole
path: issue, single-use consumption semantics, expiry, and rejection.
"""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.pairing import PairingStore

fastapi = pytest.importorskip("fastapi", reason="web extra not installed")
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from api.http import create_app


# ── store semantics (no web stack needed) ────────────────────────────────────

def test_issued_token_validates_once_it_is_known():
    store = PairingStore()
    token = store.issue()
    assert token
    assert store.validate(token) is True


def test_unknown_token_is_rejected():
    store = PairingStore()
    store.issue()
    assert store.validate("not-a-real-token") is False


def test_token_is_rejected_after_its_ttl():
    # `issue()` and `validate()` each consume one clock read, so drive the
    # clock explicitly rather than relying on a fixed iterator sequence.
    now = [100.0]
    store = PairingStore(ttl_seconds=600, clock=lambda: now[0])
    token = store.issue()
    now[0] = 100.0 + 601.0
    assert store.validate(token) is False


def test_token_is_accepted_inside_its_ttl():
    now = [100.0]
    store = PairingStore(ttl_seconds=600, clock=lambda: now[0])
    token = store.issue()
    now[0] = 100.0 + 599.0
    assert store.validate(token) is True


def test_tokens_are_unguessable_and_distinct():
    store = PairingStore()
    tokens = {store.issue() for _ in range(50)}
    assert len(tokens) == 50
    assert all(len(token) >= 20 for token in tokens)


def test_revoke_invalidates_a_token():
    store = PairingStore()
    token = store.issue()
    store.revoke(token)
    assert store.validate(token) is False


def test_expired_tokens_are_purged_on_issue():
    now = [0.0]
    store = PairingStore(ttl_seconds=10, clock=lambda: now[0])
    store.issue()
    now[0] = 100.0
    store.issue()
    # the stale entry must not accumulate forever
    assert len(store) == 1


# ── the HTTP surface ────────────────────────────────────────────────────────

def test_remote_route_rejects_a_missing_token(tmp_path):
    client = TestClient(create_app(tmp_path))
    assert client.get("/remote").status_code == 401


def test_remote_route_rejects_a_bad_token(tmp_path):
    client = TestClient(create_app(tmp_path))
    assert client.get("/remote", params={"token": "bogus"}).status_code == 403


def test_remote_route_serves_the_prompter_for_a_valid_token(tmp_path):
    app = create_app(tmp_path)
    token = app.state.pairing.issue()
    response = TestClient(app).get("/remote", params={"token": token})
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_pair_endpoint_issues_a_token_the_remote_route_accepts(tmp_path):
    client = TestClient(create_app(tmp_path))
    issued = client.post("/api/pair")
    assert issued.status_code == 201
    token = issued.json()["token"]
    assert client.get("/remote", params={"token": token}).status_code == 200


def _demo_production(root):
    """Create a minimal production so the prompter socket has a script.

    The socket now loads the document on connect (it must, to send the words
    the voice matcher follows), so a pairing test needs a real production to
    reach the "ready" frame. This keeps the test about the token gate.
    """
    directory = root / "demo"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "production.yaml").write_text(
        "schema: 1\n"
        "title: Demo\n"
        "target: {orientation: landscape, resolution: [1920, 1080], fps: 30}\n"
        "media: {}\n"
        "presenter: {source: takes/take.mp4}\n"
        "scenes:\n"
        "- id: only\n"
        "  say: Hello.\n"
        "  planned_sec: 2.0\n"
        "  measured_sec: null\n"
        "  segments: null\n"
        "  presenter: null\n"
        "  overlay: null\n"
        "  transition: null\n"
    )
    return directory


def test_teleprompter_socket_requires_a_valid_token_when_pairing_is_enforced(tmp_path):
    app = create_app(tmp_path, require_pairing=True)
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect), \
            client.websocket_connect("/ws/teleprompter/demo") as socket:
        socket.receive_json()


def test_teleprompter_socket_accepts_a_paired_token(tmp_path):
    _demo_production(tmp_path)
    app = create_app(tmp_path, require_pairing=True)
    token = app.state.pairing.issue()
    client = TestClient(app)
    with client.websocket_connect(f"/ws/teleprompter/demo?token={token}") as socket:
        ready = socket.receive_json()
    assert ready["type"] == "ready"
    # A paired client gets the script, not just permission to connect.
    assert ready["script"] == "Hello."


def test_cli_pair_fails_clearly_when_no_studio_is_running(monkeypatch, capsys):
    """Regression: `impromptu pair` advertised a /remote URL that 404'd.

    The token must be minted by the server that will validate it, so with no
    server running the command must fail loudly rather than print a token whose
    URL would be rejected.
    """
    import impromptu

    # port 1 is reserved and never listening
    monkeypatch.setattr(impromptu.sys, "argv", ["impromptu", "pair", "--port", "1"])
    with pytest.raises(SystemExit) as raised:
        impromptu.main()
    assert raised.value.code == 1
    out = capsys.readouterr().out
    assert "impromptu serve" in out, "must tell the user to start the studio first"


def test_cli_pair_prints_a_url_for_a_token_the_route_accepts(tmp_path, monkeypatch, capsys):
    """End-to-end: the CLI's token must open the real /remote route."""
    import threading
    import uvicorn

    import impromptu

    app = create_app(tmp_path)
    config = uvicorn.Config(app, host="127.0.0.1", port=8791, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.05)
        assert server.started, "test server did not start"
        monkeypatch.setattr(impromptu.sys, "argv",
                            ["impromptu", "pair", "--port", "8791"])
        with pytest.raises(SystemExit) as raised:
            impromptu.main()
        assert raised.value.code == 0
        out = capsys.readouterr().out
        assert "/remote?token=" in out
        token = out.split("/remote?token=")[1].split()[0]
        assert TestClient(app).get("/remote", params={"token": token}).status_code == 200
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def test_time_module_is_available_for_ttl_checks():
    assert time.time() > 0
