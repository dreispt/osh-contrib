"""``osh backup restore`` extension — ``--anonymize``/``--trim`` flags.

Adds the sanitize options to the restore command and overrides
``post_restore()`` — which core ``DbRestore`` runs after neutralization —
to delegate to the ``db.sanitize`` handler. Like every post-restore
extension, it is skipped under ``--dry-run`` and its failures are
reported as warnings.
"""

import click
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


class RestoreSanitize(resolve("backup.restore")):
    """Extends ``osh backup restore`` with post-restore sanitization."""

    @classmethod
    def get_options(cls):
        return [*super().get_options(), *_SANITIZE_OPTIONS]

    def post_restore(self):
        if self.anonymize or self.trim:
            # The database was just restored and neutralized, so the
            # sanitize safety prompt is satisfied by ``force=True``.
            DbSanitize(
                self.env,
                database=self.db_name,
                no_anonymize=not self.anonymize,
                no_trim=not self.trim,
                keep_days=self.keep_days,
                force=True,
            ).run()
        super().post_restore()
