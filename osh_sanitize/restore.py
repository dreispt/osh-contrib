"""Required sanitization for canonical and deprecated restore commands."""

import click
from osh.common import find_project_root
from osh.handlers import resolve

from .commands import DbSanitize

_SANITIZE_OPTIONS = [
    click.Option(
        ["--anonymize"],
        is_flag=True,
        help="Scrub PII after neutralizing (see 'osh db sanitize').",
    ),
    click.Option(
        ["--trim"],
        is_flag=True,
        help="Delete low-value rows from big tables after neutralizing "
        "(see 'osh db sanitize').",
    ),
    click.Option(
        ["--keep-days"],
        type=int,
        default=None,
        help="Days of rows to keep for 'age' trim policies (default: 30).",
    ),
]


class _RestoreSanitize:
    @classmethod
    def get_options(cls):
        return [*super().get_options(), *_SANITIZE_OPTIONS]

    def run(self):
        if (self.anonymize or self.trim) and find_project_root() is None:
            raise click.ClickException(
                "Not inside an Osh project. Restore with --anonymize or "
                "--trim from a project."
            )
        super().run()

    def run_post_restore(self):
        if not self.dry_run and (self.anonymize or self.trim):
            # Core treats optional post-restore hooks as warnings. Explicit
            # sanitization must succeed before reporting a successful restore.
            try:
                DbSanitize(
                    self.env,
                    database=self.db_name,
                    no_anonymize=not self.anonymize,
                    no_trim=not self.trim,
                    keep_days=self.keep_days,
                    force=True,
                ).run()
            except click.ClickException as exc:
                raise click.ClickException(
                    f"Restored database '{self.db_name}', but sanitization "
                    f"failed: {exc.format_message()}"
                ) from exc
        super().run_post_restore()


class RestoreSanitize(_RestoreSanitize, resolve("db.restore")):
    """Add required sanitization to the canonical restore command."""


class LegacyRestoreSanitize(_RestoreSanitize, resolve("backup.restore")):
    """Keep sanitization on the deprecated restore spelling."""
