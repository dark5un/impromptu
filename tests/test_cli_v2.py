"""CLI wiring contracts for v2 commands."""
import pytest


@pytest.mark.parametrize("command", ["boards", "render", "package", "pair", "serve"])
def test_v2_command_help_is_exposed(monkeypatch, capsys, command):
    import impromptu

    monkeypatch.setattr(impromptu.sys, "argv", ["impromptu", command, "--help"])
    with pytest.raises(SystemExit) as raised:
        impromptu.main()
    assert raised.value.code == 0
    assert command in capsys.readouterr().out


def test_direct_help_is_exposed(monkeypatch, capsys):
    import impromptu

    monkeypatch.setattr(impromptu.sys, "argv", ["impromptu", "direct", "--help"])
    with pytest.raises(SystemExit) as raised:
        impromptu.main()
    assert raised.value.code == 0
    assert "direct" in capsys.readouterr().out


def test_render_and_package_accept_production_directory(monkeypatch, capsys):
    import impromptu

    for command in ("render", "package"):
        monkeypatch.setattr(impromptu.sys, "argv", ["impromptu", command, "--help"])
        with pytest.raises(SystemExit) as raised:
            impromptu.main()
        assert raised.value.code == 0
        assert "production" in capsys.readouterr().out.lower()


def test_pair_help_has_port_option(monkeypatch, capsys):
    import impromptu

    monkeypatch.setattr(impromptu.sys, "argv", ["impromptu", "pair", "--help"])
    with pytest.raises(SystemExit) as raised:
        impromptu.main()
    assert raised.value.code == 0
    assert "port" in capsys.readouterr().out.lower()


def test_serve_help_describes_web_ui(monkeypatch, capsys):
    import impromptu

    monkeypatch.setattr(impromptu.sys, "argv", ["impromptu", "serve", "--help"])
    with pytest.raises(SystemExit) as raised:
        impromptu.main()
    assert raised.value.code == 0
    assert "web ui" in capsys.readouterr().out.lower()
