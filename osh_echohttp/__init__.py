"""osh_echohttp — print the browser URL once ``osh odoo`` is ready to serve.

Extends ``osh odoo`` with ``--open`` and ``--url-watch/--no-url-watch``
options and a ``pre_env`` step that spawns a detached ``osh _watch-url``
sidecar — it polls the Odoo HTTP port and prints ``Odoo ready: <url>`` on
the terminal (interleaved with Odoo's own log output).

Requires an osh core with the ``extends`` operation decorator.
"""

from .commands import watch_url_command
from .watcher import UrlWatch  # noqa: F401 — re-exported for extension discovery

OSH_PLUGIN_MANIFEST = {
    "commands": [watch_url_command],
}
