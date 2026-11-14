"""osh_sanitize — scrub PII and trim low-value rows from databases.

Provides ``osh db sanitize``: an anonymize step that rewrites personal
data with deterministic placeholders (the bundled anonymize profile
plus layered user/project scripts) and a trim step that deletes rows
from big, low-value tables (a bundled watchlist plus ``[trim]``
project config and ``trim`` scripts).

Also extends ``osh backup restore``: ``--anonymize``/``--trim`` run the
same steps after neutralizing, through the ``sanitize()`` hook core
``DbRestore`` calls between neutralization and ``post_restore``.

The plugin's surface is declared under ``[tool.osh]`` in
``pyproject.toml``, so the module is imported lazily — only when a
``db sanitize`` or ``backup restore`` command runs.
"""

from .commands import DbSanitize  # noqa: F401 — re-exported for discovery
from .restore import RestoreSanitize  # noqa: F401 — extension discovery
