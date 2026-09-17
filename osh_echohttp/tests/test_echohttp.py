"""Tests for the ``osh_echohttp`` plugin."""

import socket
import subprocess
import sys
import types

import pytest
from click.testing import CliRunner

from osh_echohttp.commands import watch_url_command
from osh_echohttp.watcher import pre_env_hook, resolve_http_port, wait_for_port


def _ctx(params):
    """Return a fake click Context carrying the given parsed params."""
    return types.SimpleNamespace(params=params)


def _env_spec(config_path=None):
    return types.SimpleNamespace(config_path=config_path)


# --- resolve_http_port -------------------------------------------------


def test_resolve_http_port_defaults_to_8069():
    assert resolve_http_port(()) == 8069
    assert resolve_http_port(("-d", "mydb", "--workers=0")) == 8069


def test_resolve_http_port_from_args():
    assert resolve_http_port(("--http-port=8071",)) == 8071
    assert resolve_http_port(("--http-port", "8071")) == 8071
    assert resolve_http_port(("--xmlrpc-port=8072",)) == 8072
    assert resolve_http_port(("-p", "8073")) == 8073
    assert resolve_http_port(("-p8074",)) == 8074


def test_resolve_http_port_disabled():
    assert resolve_http_port(("--no-http",)) is None
    assert resolve_http_port(("--http-port=0",)) is None


def test_resolve_http_port_from_config(tmp_path):
    conf = tmp_path / "odoo.conf"
    conf.write_text("[options]\nhttp_port = 8080\n")
    assert resolve_http_port((), conf) == 8080


def test_resolve_http_port_config_xmlrpc_fallback(tmp_path):
    conf = tmp_path / "odoo.conf"
    conf.write_text("[options]\nxmlrpc_port = 8079\n")
    assert resolve_http_port((), conf) == 8079


def test_resolve_http_port_config_http_disabled(tmp_path):
    conf = tmp_path / "odoo.conf"
    conf.write_text("[options]\nhttp_enable = False\nhttp_port = 8080\n")
    assert resolve_http_port((), conf) is None


def test_resolve_http_port_explicit_config_arg(tmp_path):
    conf = tmp_path / "custom.conf"
    conf.write_text("[options]\nhttp_port = 8090\n")
    assert resolve_http_port(("--config", str(conf))) == 8090


def test_resolve_http_port_arg_beats_config(tmp_path):
    conf = tmp_path / "odoo.conf"
    conf.write_text("[options]\nhttp_port = 8080\n")
    assert resolve_http_port(("--http-port=8071",), conf) == 8071


# --- pre_env_hook ------------------------------------------------------


@pytest.fixture
def popen_spy(monkeypatch):
    """Capture ``subprocess.Popen`` calls made by the watcher module."""
    calls = []

    def fake_popen(args, **kwargs):
        calls.append((args, kwargs))
        return types.SimpleNamespace(args=args)

    monkeypatch.setattr("osh_echohttp.watcher.subprocess.Popen", fake_popen)
    return calls


def _odoo_params(**overrides):
    params = {
        "dry_run": False,
        "url_watch": True,
        "open_browser": False,
        "extra_args": ("-d", "mydb"),
    }
    params.update(overrides)
    return params


def test_pre_env_hook_spawns_watcher(popen_spy):
    pre_env_hook(_ctx(_odoo_params()), None, _env_spec())

    assert len(popen_spy) == 1
    args, kwargs = popen_spy[0]
    assert args == [sys.executable, "-m", "osh", "_watch-url", "8069"]
    assert kwargs["start_new_session"] is True
    assert kwargs["stdin"] is subprocess.DEVNULL


def test_pre_env_hook_open_appends_flag(popen_spy):
    pre_env_hook(_ctx(_odoo_params(open_browser=True)), None, _env_spec())
    assert popen_spy[0][0][-1] == "--open"


def test_pre_env_hook_respects_port_arg(popen_spy):
    pre_env_hook(
        _ctx(_odoo_params(extra_args=("--http-port=8071",))),
        None,
        _env_spec(),
    )
    assert popen_spy[0][0][-1] == "8071"


def test_pre_env_hook_uses_env_spec_config(popen_spy, tmp_path):
    conf = tmp_path / "odoo.conf"
    conf.write_text("[options]\nhttp_port = 8080\n")
    pre_env_hook(_ctx(_odoo_params()), None, _env_spec(config_path=str(conf)))
    assert popen_spy[0][0][-1] == "8080"


@pytest.mark.parametrize(
    "params",
    [
        _odoo_params(dry_run=True),
        _odoo_params(url_watch=False),
        _odoo_params(extra_args=("shell",)),
        _odoo_params(extra_args=("neutralize", "-d", "mydb")),
        _odoo_params(extra_args=("--version",)),
        _odoo_params(extra_args=("--no-http",)),
    ],
    ids=[
        "dry_run",
        "url_watch_off",
        "shell_subcommand",
        "neutralize_subcommand",
        "version",
        "no_http",
    ],
)
def test_pre_env_hook_skips(popen_spy, params):
    pre_env_hook(_ctx(params), None, _env_spec())
    assert popen_spy == []


# --- wait_for_port -----------------------------------------------------


def test_wait_for_port_detects_listening_socket():
    with socket.socket() as srv:
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        assert wait_for_port(port, timeout=5, interval=0.05) is True


def test_wait_for_port_times_out_on_closed_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        closed_port = probe.getsockname()[1]
    assert wait_for_port(closed_port, timeout=0.3, interval=0.05) is False


# --- _watch-url command ------------------------------------------------


def test_watch_url_command_prints_url(monkeypatch):
    monkeypatch.setattr("osh_echohttp.watcher.wait_for_port", lambda *a, **k: True)
    runner = CliRunner()
    result = runner.invoke(watch_url_command, ["8071"])
    assert result.exit_code == 0
    assert "Odoo ready: http://localhost:8071" in result.output


def test_watch_url_command_opens_browser(monkeypatch):
    opened = []
    monkeypatch.setattr("osh_echohttp.watcher.wait_for_port", lambda *a, **k: True)
    monkeypatch.setattr(
        "osh_echohttp.watcher.webbrowser.open", lambda url: opened.append(url)
    )
    runner = CliRunner()
    result = runner.invoke(watch_url_command, ["8071", "--open"])
    assert result.exit_code == 0
    assert opened == ["http://localhost:8071"]


def test_watch_url_command_times_out_silently(monkeypatch):
    monkeypatch.setattr("osh_echohttp.watcher.wait_for_port", lambda *a, **k: False)
    runner = CliRunner()
    result = runner.invoke(watch_url_command, ["8071"])
    assert result.exit_code == 1
    assert "Odoo ready" not in result.output


def test_watch_url_command_honours_timeout_env(monkeypatch):
    """``OSH_URL_WATCH_TIMEOUT`` bounds the real polling loop."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        closed_port = probe.getsockname()[1]
    monkeypatch.setenv("OSH_URL_WATCH_TIMEOUT", "0.2")
    runner = CliRunner()
    result = runner.invoke(watch_url_command, [str(closed_port)])
    assert result.exit_code == 1


# --- manifest ----------------------------------------------------------


def test_manifest_declares_hooks_and_command():
    from osh_echohttp import OSH_PLUGIN_MANIFEST

    hooks = OSH_PLUGIN_MANIFEST["hooks"]
    assert set(hooks) == {"odoo.options", "odoo.pre_env"}
    assert len(hooks["odoo.options"]) == 2
    assert hooks["odoo.pre_env"] == [pre_env_hook]
    assert watch_url_command in OSH_PLUGIN_MANIFEST["commands"]
    assert watch_url_command.hidden is True
