"""``osh odoo --kiri-share`` — public sharing for the Odoo run.

Extends the core ``odoo`` command in place: ``--kiri-share`` starts
``kiri share <port> --json`` under a supervisor before Odoo runs and
prints the public ``*.runkiri.cloud`` URL. The share is tied to the
run's lifetime through a lifeline pipe the Odoo process inherits — it
ends when Odoo ends, however Odoo ends.
"""

import shlex
import shutil

import click
from osh import echo
from osh.commands.odoo_cmd import OdooRun
from osh.common import odoo_http_port

from .share import start_share

_NO_HTTP_ARGS = ("--no-http", "--stop-after-init", "--help", "-h", "--version")


class OdooKiriShare(OdooRun):
    """Add ``--kiri-share``/``--kiri-share-name`` to ``osh odoo``."""

    kiri_share = False
    kiri_share_name = None
    _share_session = None

    @click.option(
        "--kiri-share",
        is_flag=True,
        help="Also make this Odoo publicly available on the Internet "
        "through Kiri Share while it runs — anyone with the link can "
        "open it.",
    )
    @click.option(
        "--kiri-share-name",
        metavar="NAME",
        help="Reserve NAME.runkiri.cloud for the public link "
        "(implies --kiri-share).",
    )
    def run(self):
        super().run()

    def pre_env(self):
        super().pre_env()
        self._start_kiri_share()

    def execute(self):
        """End the share's lifeline when the run returns without exec'ing.

        On the exec path ``os.execvp`` replaces this process — the
        inheritable lifeline write end passes to Odoo and the share ends
        when Odoo exits. When ``execute()`` returns instead (``--wait``,
        ``--dry-run``, a failed exec) closing the lifeline ends the share
        here.
        """
        try:
            super().execute()
        finally:
            if self._share_session is not None:
                self._share_session.close()
                self._share_session = None

    def _start_kiri_share(self):
        """Start ``kiri share`` for this run — or warn, preview, skip."""
        if not (self.kiri_share or self.kiri_share_name):
            return
        if self.has_subcommand or any(arg in _NO_HTTP_ARGS for arg in self.extra_args):
            echo.warning(
                "--kiri-share is ignored: this run does not serve HTTP "
                "(an Odoo subcommand or a no-HTTP option was given)."
            )
            return
        port = self._share_port()
        argv = ["kiri", "share", str(port), "--json"]
        if self.kiri_share_name:
            argv += ["--name", self.kiri_share_name]
        if self.dry_run:
            echo.info(f"Would share: {shlex.join(argv)}")
            return
        if shutil.which("kiri") is None:
            raise click.ClickException(
                "kiri not found on PATH. Install Kiri: https://runkiri.com/download"
            )
        self._share_session = start_share(argv)
        echo.info(f"Odoo (public): {self._share_session.url}", err=True)

    def _share_port(self):
        """Return the port ``kiri share`` forwards to Odoo."""
        port = odoo_http_port(self.extra_args)
        if port is not None:
            return port
        return self.runtime.odoo_port(self.base) or 8069
