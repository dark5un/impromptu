"""Phase 3 board rendering contract tests."""
from pathlib import Path

import pytest

from render.board import (
    BoardDurationError,
    board_cache_key,
    build_boards,
    extract_duration,
    hyperframes_command,
    render_template,
    starter_templates,
    validate_duration,
)


def test_extract_duration_reads_root_data_attribute():
    html = '<div id="root" data-duration="23.4"></div>'
    assert extract_duration(html) == pytest.approx(23.4)


def test_duration_guard_allows_one_frame_but_rejects_two():
    assert validate_duration(10.033, 10.0, fps=30)
    with pytest.raises(BoardDurationError, match="duration"):
        validate_duration(10.067, 10.0, fps=30)


def test_cache_key_changes_with_html_or_duration():
    first = board_cache_key(b"<html>a</html>", 10.0)
    assert first == board_cache_key(b"<html>a</html>", 10.0)
    assert first != board_cache_key(b"<html>b</html>", 10.0)
    assert first != board_cache_key(b"<html>a</html>", 10.1)


def test_starter_templates_are_named_factories():
    assert set(starter_templates()) == {"title_card", "bar_chart", "lower_third", "code_reveal"}
    assert all(callable(factory) for factory in starter_templates().values())


def test_hyperframes_command_uses_mov_and_fps(tmp_path):
    command = hyperframes_command(tmp_path / "board.html", tmp_path / "board.mov", 30)
    assert command == [
        "hyperframes", "render", str(tmp_path), "--composition", "board.html",
        "--output", str(tmp_path / "board.mov"), "--format", "mov", "--fps", "30",
    ]


@pytest.mark.parametrize("name", ["title_card", "bar_chart", "lower_third", "code_reveal"])
def test_starter_templates_have_orientation_contract(name):
    assert name in starter_templates()
    landscape = render_template(name, duration=4.0, orientation="landscape")
    vertical = render_template(name, duration=4.0, orientation="vertical")
    assert 'data-duration="4.0"' in landscape
    assert 'data-width="1920"' in landscape and 'data-height="1080"' in landscape
    assert 'data-width="1080"' in vertical and 'data-height="1920"' in vertical
    assert '<script src="/vendor/gsap.min.js"></script>' in landscape
    assert 'window.__timelines["main"]' in landscape


def test_build_boards_renders_named_board_entries_and_caches(tmp_path):
    board = tmp_path / "boards" / "chart.html"
    board.parent.mkdir()
    board.write_text('<div id="root" data-duration="2.0"></div>')
    document = {
        "target": {"fps": 30},
        "media": {"chart": {"type": "board", "src": "boards/chart.html"}},
        "scenes": [{"overlay": "chart", "measured_sec": 2.0}],
    }
    calls = []
    def runner(command, check):
        calls.append((command, check))
        # A board build is two stages: HyperFrames writes straight alpha to a
        # staged path, then ffmpeg premultiplies it into the cache path.
        if "--output" in command:
            Path(command[command.index("--output") + 1]).write_bytes(b"mov")
        else:
            Path(command[-1]).write_bytes(b"premultiplied mov")
    first = build_boards(document, root=tmp_path, runner=runner, vendor=False)
    second = build_boards(document, root=tmp_path, runner=runner, vendor=False)
    assert first["chart"].suffix == ".mov"
    assert second == first
    # Two calls for the first build (render + premultiply), none for the second:
    # the content-addressed cache must not re-render an unchanged board.
    assert len(calls) == 2
    assert "--format" in calls[0][0] and "mov" in calls[0][0]
    assert calls[1][0][0] == "ffmpeg" and "premultiply=inplace=1" in calls[1][0]
    # The cache entry holds the premultiplied artifact, not the raw render.
    assert first["chart"].read_bytes() == b"premultiplied mov"
    assert not first["chart"].with_suffix(".straight.mov").exists()


def test_build_boards_rejects_scene_duration_mismatch(tmp_path):
    board = tmp_path / "chart.html"
    board.write_text('<div id="root" data-duration="2.0"></div>')
    document = {
        "target": {"fps": 30},
        "media": {"chart": {"type": "board", "src": "chart.html"}},
        "scenes": [{"overlay": "chart", "measured_sec": 2.1}],
    }
    with pytest.raises(BoardDurationError):
        build_boards(document, root=tmp_path, runner=lambda *_: None)


def test_build_boards_rejects_invalid_orientation():
    with pytest.raises(ValueError, match="orientation"):
        render_template("title_card", duration=1, orientation="square")


def test_build_boards_requires_measured_duration(tmp_path):
    board = tmp_path / "chart.html"
    board.write_text('<div id="root" data-duration="2.0"></div>')
    document = {
        "target": {"fps": 30},
        "media": {"chart": {"type": "board", "src": "chart.html"}},
        "scenes": [{"overlay": "chart", "measured_sec": None}],
    }
    with pytest.raises(BoardDurationError, match="measured_sec"):
        build_boards(document, root=tmp_path, runner=lambda *_: None)


def test_cli_exposes_boards_command(monkeypatch, capsys):
    import impromptu

    monkeypatch.setattr(impromptu.sys, "argv", ["impromptu", "boards", "--help"])
    with pytest.raises(SystemExit) as raised:
        impromptu.main()
    assert raised.value.code == 0
    assert "HyperFrames" in capsys.readouterr().out


__all__ = []


# ── offline GSAP vendoring ───────────────────────────────────────────────────

def test_vendor_gsap_stages_the_local_asset(tmp_path):
    """Boards load /vendor/gsap.min.js; the file must exist beside them.

    Proven by a real render: without it HyperFrames reaches 75%, launches
    Chrome, then aborts with sub_timeline_script_failure because the stock
    template's cdn.jsdelivr.net URL is unreachable in the container.
    """
    from render.board import vendor_gsap

    source = tmp_path / "src" / "gsap.min.js"
    source.parent.mkdir(parents=True)
    source.write_text("/* gsap */")
    project = tmp_path / "proj"
    project.mkdir()

    staged = vendor_gsap(project, source=source)

    assert staged == project / "vendor" / "gsap.min.js"
    assert staged.read_text() == "/* gsap */"


def test_vendor_gsap_reports_a_missing_source(tmp_path):
    from render.board import BoardError, vendor_gsap

    with pytest.raises(BoardError, match="gsap"):
        vendor_gsap(tmp_path, source=tmp_path / "absent" / "gsap.min.js")


def test_starter_templates_reference_the_local_vendor_path():
    from render.board import STARTER_TEMPLATES, render_template

    for name in STARTER_TEMPLATES:
        html = render_template(name, duration=3.0)
        assert "/vendor/gsap.min.js" in html
        assert "jsdelivr" not in html, "a CDN link cannot render offline"
