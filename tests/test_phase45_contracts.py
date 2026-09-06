"""RED tests for the Phase 4-5 delivery surface."""
import hashlib
import importlib
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


def test_upload_hash_is_content_addressed():
    http = importlib.import_module("api.http")
    payload = b"hello phase five"
    assert http.content_hash(payload) == hashlib.sha256(payload).hexdigest()


def test_safe_production_name_rejects_path_traversal():
    http = importlib.import_module("api.http")
    assert http.safe_production_name("chapter-1") == "chapter-1"
    with pytest.raises(ValueError):
        http.safe_production_name("../outside")
    with pytest.raises(ValueError):
        http.safe_production_name("a/b")


def test_create_and_list_production_dirs(tmp_path):
    http = importlib.import_module("api.http")
    created = http.create_production(tmp_path, "chapter-1")
    assert created == tmp_path / "chapter-1"
    assert {item.name for item in http.list_productions(tmp_path)} == {"chapter-1"}
    assert (created / "media").is_dir()
    assert (created / "takes").is_dir()
    assert (created / "out").is_dir()


def test_validate_production_file_reports_document_errors(tmp_path):
    http = importlib.import_module("api.http")
    path = tmp_path / "production.yaml"
    path.write_text("schema: 1\n")
    errors = http.validate_production_file(path)
    assert errors
    assert any("title" in error for error in errors)


def test_mcp_has_explicit_optional_dependency_boundary():
    mcp = importlib.import_module("api.mcp")
    if mcp.FASTMCP_IMPORT_ERROR is not None:
        with pytest.raises(RuntimeError, match="fastmcp"):
            mcp.get_mcp()


def test_container_and_quadlet_contracts():
    container = (ROOT / "containers/Containerfile").read_text()
    quadlet = (ROOT / "quadlets/studio.container").read_text()
    assert "MLT" in container or "mlt" in container
    assert "ffmpeg" in container
    assert "whisper" in container.lower()
    assert "chrome-headless-shell" in container
    assert "PRODUCER_HEADLESS_SHELL_PATH" in container
    assert "COPY --from=hyperframes-render /usr/local/lib/node_modules" in container
    assert "ARG TARGETARCH" in container
    assert "PublishPort=127.0.0.1:8787" in quadlet
    assert "Network=ai.network" in quadlet
    assert "UserNS=keep-id" in quadlet
    assert "%h/workspace/videos" in quadlet


def test_headless_shell_path_is_resolved_not_a_stale_literal():
    """Regression: ENV pointed at /opt/chrome-headless-shell, which never existed.

    The wrapper script found the real browser but a direct `hyperframes` call
    (which render/board.py makes) inherited the broken path and silently lost
    BeginFrame capture.
    """
    container = (ROOT / "containers/Containerfile").read_text()
    assert "PRODUCER_HEADLESS_SHELL_PATH=/opt/chrome-headless-shell" not in container
    # the path must be discovered at build time and symlinked to a stable name
    assert "ln -sf" in container
    assert "/usr/local/bin/chrome-headless-shell" in container


def test_hyperframes_bin_is_a_symlink_not_a_flattened_copy():
    """Regression: the CLI was dead on arrival in the image.

    `COPY /usr/local/bin/hyperframes` flattens npm's symlink into a plain file,
    so its relative `../dist/...` imports resolve against /usr/local/ and the
    CLI dies with ERR_MODULE_NOT_FOUND for /usr/local/dist/runtimeVersion.js.
    The bin must be re-linked into the package directory, and the build must
    smoke-test it so a broken CLI cannot ship.
    """
    container = (ROOT / "containers/Containerfile").read_text()
    assert "COPY --from=hyperframes-render /usr/local/bin/hyperframes" not in container
    assert "ln -sf" in container
    assert "hyperframes --version" in container, "build must smoke-test the CLI"


def test_whisper_build_failure_is_not_swallowed():
    """`|| true` would ship an image whose reconcile silently cannot run."""
    container = (ROOT / "containers/Containerfile").read_text()
    assert "/usr/local/bin/whisper-cli || true" not in container


def test_productions_root_is_configurable_by_environment(monkeypatch, tmp_path):
    """The quadlet sets IMPROMPTU_PRODUCTIONS; the app must actually read it."""
    http = importlib.import_module("api.http")
    if http.FASTAPI_IMPORT_ERROR is not None:
        pytest.skip("web extra not installed")
    monkeypatch.setenv("IMPROMPTU_PRODUCTIONS", str(tmp_path / "prods"))
    http.create_app()
    assert (tmp_path / "prods").is_dir()


def test_quadlet_productions_env_matches_its_volume_mount():
    quadlet = (ROOT / "quadlets/studio.container").read_text()
    assert "IMPROMPTU_PRODUCTIONS=/app/videos" in quadlet
    assert ":/app/videos:Z" in quadlet


def test_web_ui_contains_api_and_prompter_hooks():
    html = (ROOT / "web/index.html").read_text()
    js = (ROOT / "web/static/app.js").read_text()
    assert "production" in html.lower()
    assert "/api/productions" in js
    assert "WebSocket" in js
    assert "pause" in js.lower()


def test_cli_exposes_serve_parser(monkeypatch, capsys):
    import impromptu

    monkeypatch.setattr(impromptu.sys, "argv", ["impromptu", "serve", "--help"])
    with pytest.raises(SystemExit) as raised:
        impromptu.main()
    assert raised.value.code == 0
    assert "web UI" in capsys.readouterr().out


def test_pyproject_declares_optional_web_stack():
    text = (ROOT / "pyproject.toml").read_text()
    assert "fastapi" in text
    assert "fastmcp" in text
    assert "uvicorn" in text
    assert "web" in text
