"""Internal ``osh _watch-url`` command spawned by ``osh_echohttp``."""

import click

from .watcher import watch_url


@click.command(name="_watch-url", hidden=True)
@click.argument("port", type=int)
@click.option(
    "--open",
    "open_browser",
    is_flag=True,
    help="Open the URL in the default browser once ready.",
)
def watch_url_command(port, open_browser):
    """Poll localhost:PORT until Odoo accepts connections, then print the URL.

    Internal helper: ``osh odoo`` spawns this as a detached sidecar right
    before exec'ing the Odoo server. Not meant to be invoked directly.
    """
    raise SystemExit(watch_url(port, open_browser=open_browser))
