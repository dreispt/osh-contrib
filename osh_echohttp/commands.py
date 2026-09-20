"""Internal ``osh echohttp`` sidecar command spawned by ``osh_echohttp``."""

import click
from osh.cli_utils import handler_command
from osh.handlers import CommandHandler

from .watcher import watch_url


class EchoHttp(CommandHandler):
    """Poll localhost:PORT until Odoo accepts connections, then print the URL.

    Internal helper: ``osh odoo`` spawns this as a detached sidecar right
    before exec'ing the Odoo server. DBNAME, when given, is used as a
    ``localhost`` subdomain in the printed URL. Not meant to be invoked
    directly.
    """

    _cli_name = "echohttp"
    _cli_hidden = True

    port = None
    dbname = None
    open_browser = False

    @click.argument("port", type=int)
    @click.argument("dbname", required=False)
    @click.option(
        "--open",
        "open_browser",
        is_flag=True,
        help="Open the URL in the default browser once ready.",
    )
    def run(self):
        raise SystemExit(
            watch_url(self.port, db_name=self.dbname, open_browser=self.open_browser)
        )


#: Standalone ``echohttp`` command — used by tests; the CLI wires the same
#: handler through the ``[commands]`` declaration.
echohttp = handler_command("echohttp", EchoHttp)
