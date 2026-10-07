"""osh_update — update Odoo modules whose code changed since the last run.

Provides the ``osh db update`` command: it fingerprints project modules
(code and data files; ``static/`` is ignored), compares them to fingerprints
stored in the target database's ``ir.config_parameter``
(``osh.module_fingerprints``) and runs ``odoo -u`` on the installed modules
that changed. The first run only records a baseline — no update is performed.

Also provides ``osh db installed`` — a listing of the modules recorded in a
database with their installed version and state.

Also extends ``osh backup restore``: when a restore brings in a dump without
stored fingerprints, a local baseline is recorded right away so later
``osh db update`` runs diff from the restore point.

The plugin's surface is declared under ``[tool.osh]`` in ``pyproject.toml``,
so the module is imported lazily — only when a ``db`` subcommand or
``osh backup restore`` runs.
"""

from .commands import DbInstalled, DbUpdate  # noqa: F401 — re-exported for discovery
from .core import RestoreBaseline  # noqa: F401 — re-exported for extension discovery
