"""Odoo URL watcher for the ``osh odoo`` command.

``osh odoo`` hands off to Odoo via ``exec``, so the ``UrlWatch`` extension's
``pre_env`` spawns a detached ``osh echohttp`` sidecar process right
before the handoff. The sidecar polls the Odoo HTTP port and, once the server
actually answers a database-bound request, prints the browser URL on the
inherited terminal (interleaved with Odoo's own log output) and optionally
opens a browser tab.

A bare TCP accept is not enough: Odoo binds the HTTP socket before the
database registry is loaded, so a first run that initializes the database
would report "ready" minutes early. Requesting a db-bound page blocks on
the registry until module loading finishes, so the first real HTTP
response is the true ready signal.
"""

import configparser
import http.client
import os
import re
import subprocess
import sys
import time
import webbrowser
from urllib.parse import quote

import click
from osh.commands.odoo_cmd import OdooRun

DEFAULT_PORT = 8069
# Generous bound: "ready" now means answering a db-bound request, which
# only happens after a first run finishes initializing the database.
DEFAULT_TIMEOUT = 600.0
POLL_INTERVAL = 0.5
REQUEST_TIMEOUT = 2.0
READY_DELAY = 2.0
_PORT_ARGS = ("--http-port", "--xmlrpc-port", "--xmlrpc_port", "-p")
_CONFIG_ARGS = ("--config", "-c")
_NO_SERVER_ARGS = ("--version", "--help", "-h", "--stop-after-init")


class UrlWatch(OdooRun):
    """Extends ``osh odoo`` — spawn the URL watcher for plain server runs.

    Adds ``--open`` and ``--url-watch/--no-url-watch`` options — stacked
    on ``run()`` so ``get_options`` picks them up across the MRO — and
    spawns the detached sidecar in ``pre_env``. Skips
    dry runs, explicitly disabled runs (``--no-url-watch``/
    ``OSH_URL_WATCH=0``), Odoo subcommands such as ``shell``, and
    invocations that never serve HTTP (``--version``, ``--help``,
    ``--stop-after-init``, ``--no-http``, ``http_port = 0``).

    The sidecar is the hidden ``osh echohttp`` command declared by this
    plugin (see ``commands.py``).
    """

    url_watch = True
    open_browser = False

    @click.option(
        "--open",
        "open_browser",
        is_flag=True,
        help="Open the Odoo URL in the browser once the server is ready.",
    )
    @click.option(
        "--url-watch/--no-url-watch",
        default=True,
        envvar="OSH_URL_WATCH",
        help="Print the browser URL once Odoo is ready (default: on; "
        "OSH_URL_WATCH=0 disables).",
    )
    def run(self):
        # The override exists only to carry the option declarations.
        super().run()

    def pre_env(self):
        super().pre_env()
        extra_args = self.extra_args or ()
        if self.dry_run or not self.url_watch:
            return
        if self.has_subcommand or any(a in extra_args for a in _NO_SERVER_ARGS):
            return
        port = resolve_http_port(extra_args, self.env_spec.config_path)
        if port:
            spawn_url_watcher(
                port,
                db_name=getattr(self.env_spec, "db_name", None),
                open_browser=self.open_browser,
            )


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


def spawn_url_watcher(port, *, db_name=None, open_browser=False):
    """Spawn a detached ``osh echohttp`` process for *port*.

    The sidecar runs in its own session so it survives the ``exec`` that
    replaces this process with Odoo, and keeps writing to the same terminal.
    It self-terminates after the ``watch_url`` timeout or as soon as the
    spawning run exits.
    """
    args = [sys.executable, "-m", "osh", "echohttp", str(port)]
    if db_name:
        args.append(db_name)
    if open_browser:
        args.append("--open")
    return subprocess.Popen(args, stdin=subprocess.DEVNULL, start_new_session=True)


def watch_url(port, *, db_name=None, open_browser=False):
    """Poll *port* until Odoo is ready, print the URL, maybe open a browser.

    Returns the process exit code: 0 when Odoo answers a request that
    requires a loaded registry, 1 on timeout or when the spawning
    process is gone (silent — Odoo's own logs already report boot
    failures). After the response, the echo is held back for
    ``READY_DELAY`` seconds so Odoo's own startup log lines land first.
    The timeout defaults to ``DEFAULT_TIMEOUT`` seconds and can be
    overridden with the ``OSH_URL_WATCH_TIMEOUT`` environment variable.
    """
    try:
        timeout = float(os.environ.get("OSH_URL_WATCH_TIMEOUT", DEFAULT_TIMEOUT))
    except ValueError:
        timeout = DEFAULT_TIMEOUT
    # A request pinned to the database blocks on the registry while
    # modules load, so the first answer means Odoo is really serving.
    # Without a database name there is nothing to initialize; any
    # answer is good enough.
    path = f"/web/login?db={quote(db_name)}" if db_name else "/web/health"
    # The sidecar's parent is the `osh` process that execs Odoo — same
    # PID before and after the exec. If it is gone, this watcher is a
    # leftover from a previous run and must stay silent.
    if not wait_for_http(port, path, timeout=timeout, parent_pid=os.getppid()):
        return 1
    time.sleep(READY_DELAY)
    subdomain = _db_subdomain(db_name)
    host = f"{subdomain}.localhost" if subdomain else "localhost"
    url = f"http://{host}:{port}"
    click.echo(f"\n🚀 Odoo ready: {url}", err=True)
    if open_browser:
        webbrowser.open(url)
    return 0


def wait_for_http(
    port,
    path,
    *,
    host="127.0.0.1",
    timeout=DEFAULT_TIMEOUT,
    interval=POLL_INTERVAL,
    parent_pid=None,
):
    """Poll until a ``GET path`` on *host:port* gets an HTTP response.

    Any HTTP status counts as ready — the point is that the server is
    dispatching requests, not that this particular page exists. A bare
    TCP accept is not enough: Odoo binds the socket before the registry
    is loaded, so connections succeed while the database is still
    initializing. The db-bound probe stalls on the registry lock and
    its response only arrives once module loading finished.

    When *parent_pid* is given, stop polling as soon as the spawning
    process is gone: the sidecar is detached, so it is reparented the
    moment its ``osh odoo`` run exits, and a watcher whose run is over
    must never report on a later server bound to the same port. (On
    Windows the parent PID does not change on orphaning — the timeout
    remains the bound there.)
    """
    deadline = time.monotonic() + timeout
    while True:
        if parent_pid is not None and os.getppid() != parent_pid:
            return False
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        conn = http.client.HTTPConnection(
            host, port, timeout=min(REQUEST_TIMEOUT, remaining)
        )
        try:
            conn.request("GET", path)
            conn.getresponse().read()
            return True
        except (OSError, http.client.HTTPException):
            pass
        finally:
            conn.close()
        time.sleep(min(interval, max(0.0, deadline - time.monotonic())))


def _db_subdomain(db_name):
    """Return *db_name* as a DNS-safe ``localhost`` subdomain, or None."""
    if not db_name:
        return None
    slug = re.sub(r"[^a-z0-9-]+", "-", str(db_name).lower()).strip("-")
    return slug or None


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
