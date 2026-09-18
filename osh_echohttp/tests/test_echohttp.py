"""Tests for the ``osh_echohttp`` plugin."""

import socket
import subprocess
import sys
import types

import pytest
from click.testing import CliRunner
from osh.commands.odoo_cmd import OdooRun
from osh.operations import Env

from osh_echohttp.commands import watch_url_command
from osh_echohttp.watcher import UrlWatch, resolve_http_port, wait_for_port


def _odoo_op(params, env_spec=None):
    """Return the ``odoo`` operation extended by UrlWatch, ready for pre_env."""
    cls = type("OdooWithUrlWatch", (UrlWatch, OdooRun), {})
    ctx = types.SimpleNamespace(params=params)
    op = cls(Env(ctx), **params)
    op.env_spec = env_spec or types.SimpleNamespace(config_path=None, db_name=None)
    return op


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


# --- UrlWatch.pre_env --------------------------------------------------


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


def _env_spec(config_path=None, db_name=None):
    return types.SimpleNamespace(config_path=config_path, db_name=db_name)


def test_pre_env_spawns_watcher(popen_spy):
    _odoo_op(_odoo_params()).pre_env()

    assert len(popen_spy) == 1
    args, kwargs = popen_spy[0]
    assert args == [sys.executable, "-m", "osh", "_watch-url", "8069"]
    assert kwargs["start_new_session"] is True
    assert kwargs["stdin"] is subprocess.DEVNULL


def test_pre_env_open_appends_flag(popen_spy):
    _odoo_op(_odoo_params(open_browser=True)).pre_env()
    assert popen_spy[0][0][-1] == "--open"


def test_pre_env_respects_port_arg(popen_spy):
    _odoo_op(_odoo_params(extra_args=("--http-port=8071",))).pre_env()
    assert popen_spy[0][0][-1] == "8071"


def test_pre_env_passes_db_name(popen_spy):
    _odoo_op(_odoo_params(), _env_spec(db_name="mydb")).pre_env()
    assert popen_spy[0][0][-2:] == ["8069", "mydb"]


def test_pre_env_uses_env_spec_config(popen_spy, tmp_path):
    conf = tmp_path / "odoo.conf"
    conf.write_text("[options]\nhttp_port = 8080\n")
    _odoo_op(_odoo_params(), _env_spec(config_path=str(conf))).pre_env()
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
def test_pre_env_skips(popen_spy, params):
    _odoo_op(params).pre_env()
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
    assert "🚀 Odoo ready: http://localhost:8071" in result.output


def test_watch_url_command_prints_db_subdomain(monkeypatch):
    monkeypatch.setattr("osh_echohttp.watcher.wait_for_port", lambda *a, **k: True)
    runner = CliRunner()
    result = runner.invoke(watch_url_command, ["8071", "My_DB"])
    assert result.exit_code == 0
    assert "🚀 Odoo ready: http://my-db.localhost:8071" in result.output


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


def test_manifest_declares_command_and_url_watch_extends_odoo():
    from osh_echohttp import OSH_PLUGIN_MANIFEST

    assert "odoo" in UrlWatch._extends
    assert watch_url_command in OSH_PLUGIN_MANIFEST["commands"]
    assert watch_url_command.hidden is True


def test_url_watch_get_options():
    """The extension contributes ``--open`` and ``--url-watch`` options."""
    cls = type("OdooWithUrlWatch", (UrlWatch, OdooRun), {})
    names = {p.name for p in cls.get_options()}
    assert {"open_browser", "url_watch"} <= names
