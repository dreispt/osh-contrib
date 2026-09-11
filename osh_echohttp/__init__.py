"""osh_echohttp — print the browser URL once ``osh odoo`` is ready to serve.

Adds ``--open`` and ``--url-watch/--no-url-watch`` options to ``osh odoo``
and hooks the pre-env phase to spawn a detached ``osh _watch-url`` sidecar
that polls the Odoo HTTP port and prints ``Odoo ready: <url>`` on the
terminal (interleaved with Odoo's own log output).

Requires an osh core that supports the ``hooks`` manifest key.
"""

import click
from osh.hooks import HOOK_ODOO_OPTIONS, HOOK_ODOO_PRE_ENV

from .commands import watch_url_command
from .watcher import pre_env_hook

_OPEN_OPTION = click.Option(
    ["--open", "open_browser"],
    is_flag=True,
    help="Open the Odoo URL in the browser once the server is ready.",
)

_URL_WATCH_OPTION = click.Option(
    ["--url-watch/--no-url-watch"],
    default=True,
    envvar="OSH_URL_WATCH",
    help="Print the browser URL once Odoo is ready (default: on; "
    "OSH_URL_WATCH=0 disables).",
)

OSH_PLUGIN_MANIFEST = {
    "commands": [watch_url_command],
    "hooks": {
        HOOK_ODOO_OPTIONS: [_OPEN_OPTION, _URL_WATCH_OPTION],
        HOOK_ODOO_PRE_ENV: [pre_env_hook],
    },
}
