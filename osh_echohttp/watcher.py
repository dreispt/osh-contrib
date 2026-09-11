"""Odoo URL watcher for the ``osh odoo`` command.

``osh odoo`` hands off to Odoo via ``exec``, so this module's ``pre_env_hook``
spawns a detached ``osh _watch-url`` sidecar process right before the handoff.
The sidecar polls the Odoo HTTP port and, once the server accepts TCP
connections, prints the browser URL on the inherited terminal (interleaved
with Odoo's own log output) and optionally opens a browser tab.
"""

import configparser
import os
import socket
import subprocess
import sys
import time
import webbrowser

import click

DEFAULT_PORT = 8069
DEFAULT_TIMEOUT = 120.0
POLL_INTERVAL = 0.5
_PORT_ARGS = ("--http-port", "--xmlrpc-port", "--xmlrpc_port")
_CONFIG_ARGS = ("--config", "-c")
_NO_SERVER_ARGS = ("--version", "--help", "-h")


def pre_env_hook(ctx, base, env_spec):
    """Spawn the URL watcher sidecar for plain ``osh odoo`` server runs.

    Registered under the ``odoo.pre_env`` hook point. Skips dry runs,
    explicitly disabled runs (``--no-url-watch``/``OSH_URL_WATCH=0``), Odoo
    subcommands such as ``shell``, and invocations that never start the HTTP
    server (``--version``, ``--help``, ``--no-http``, ``http_port = 0``).
    """
    params = ctx.params
    extra_args = params.get("extra_args") or ()
    if params.get("dry_run") or not params.get("url_watch", True):
        return
    has_subcommand = extra_args and not extra_args[0].startswith("-")
    if has_subcommand or any(a in extra_args for a in _NO_SERVER_ARGS):
        return
    port = resolve_http_port(extra_args, env_spec.config_path)
    if port:
        spawn_url_watcher(port, open_browser=params.get("open_browser", False))


def resolve_http_port(extra_args, conf_path=None):
    """Return the Odoo HTTP port for this run, or ``None`` if HTTP is off.

    Precedence: ``--http-port``/``--xmlrpc-port`` pass-through arguments, then
    ``http_port``/``xmlrpc_port`` in the effective config file (an explicit
    ``--config`` argument or the generated *conf_path*), then the Odoo
    default 8069. Returns ``None`` when the HTTP service is disabled
    (``--no-http``, a port of 0, or ``http_enable = false``).
    """
    if "--no-http" in extra_args:
        return None
    value = _arg_value(extra_args, _PORT_ARGS)
    if value is None:
        config_arg = _arg_value(extra_args, _CONFIG_ARGS)
        value = _port_from_config(config_arg or conf_path)
    if value is None:
        return DEFAULT_PORT
    try:
        port = int(str(value).strip())
    except ValueError:
        return DEFAULT_PORT
    return port or None


def spawn_url_watcher(port, *, open_browser=False):
    """Spawn a detached ``osh _watch-url`` process for *port*.

    The sidecar runs in its own session so it survives the ``exec`` that
    replaces this process with Odoo, and keeps writing to the same terminal.
    It self-terminates after the ``watch_url`` timeout.
    """
    args = [sys.executable, "-m", "osh", "_watch-url", str(port)]
    if open_browser:
        args.append("--open")
    return subprocess.Popen(args, stdin=subprocess.DEVNULL, start_new_session=True)


def wait_for_port(
    port, *, host="127.0.0.1", timeout=DEFAULT_TIMEOUT, interval=POLL_INTERVAL
):
    """Poll until *host:port* accepts a TCP connection; return success."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except OSError:
            time.sleep(interval)
    return False


def watch_url(port, *, open_browser=False):
    """Poll *port* until Odoo is ready, print the URL, maybe open a browser.

    Returns the process exit code: 0 when the port became ready, 1 on
    timeout (silent — Odoo's own logs already report boot failures). The
    timeout defaults to ``DEFAULT_TIMEOUT`` seconds and can be overridden
    with the ``OSH_URL_WATCH_TIMEOUT`` environment variable.
    """
    try:
        timeout = float(os.environ.get("OSH_URL_WATCH_TIMEOUT", DEFAULT_TIMEOUT))
    except ValueError:
        timeout = DEFAULT_TIMEOUT
    if not wait_for_port(port, timeout=timeout):
        return 1
    url = f"http://localhost:{port}"
    click.echo(f"\nOdoo ready: {url}", err=True)
    if open_browser:
        webbrowser.open(url)
    return 0


def _arg_value(args, names):
    """Return the value of the first matching option in *args*.

    Handles ``--opt=value`` and ``--opt value`` forms, plus the glued short
    form ``-cvalue``.
    """
    for i, arg in enumerate(args):
        for name in names:
            if arg == name:
                value = args[i + 1] if i + 1 < len(args) else None
                if value and not value.startswith("-"):
                    return value
                return None
            if arg.startswith(f"{name}="):
                return arg.split("=", 1)[1]
            if (
                not name.startswith("--")
                and arg.startswith(name)
                and len(arg) > len(name)
                and arg[len(name)] != "-"
            ):
                return arg[len(name) :]
    return None


def _port_from_config(path):
    """Return the port configured in *path*, 0 when HTTP is disabled, or None."""
    if not path:
        return None
    cfg = configparser.ConfigParser()
    if not cfg.read(str(path), encoding="utf-8"):
        return None
    if not cfg.has_section("options"):
        return None
    options = cfg["options"]
    if options.get("http_enable", "true").strip().lower() in (
        "0",
        "false",
        "no",
        "off",
    ):
        return 0
    for key in ("http_port", "xmlrpc_port"):
        if key in options:
            return options[key]
    return None
