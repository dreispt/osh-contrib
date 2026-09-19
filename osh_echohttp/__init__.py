"""osh_echohttp — print the browser URL once ``osh odoo`` is ready to serve.

Extends ``osh odoo`` with ``--open`` and ``--url-watch/--no-url-watch``
options and a ``pre_env`` step that spawns a detached ``osh echohttp``
sidecar — it polls the Odoo HTTP port and prints ``Odoo ready: <url>`` on
the terminal (interleaved with Odoo's own log output).

Both the extension and the hidden sidecar command are declared in
``osh-plugin.toml``, so the module is imported lazily — only when
``osh odoo`` or ``osh echohttp`` actually runs.
"""

from .commands import EchoHttp  # noqa: F401 — re-exported for discovery
from .watcher import UrlWatch  # noqa: F401 — re-exported for extension discovery
