"""osh_update — install and update Odoo modules, tracking code changes.

Provides the ``osh apps update`` command: it fingerprints project modules
(code and data files; ``static/`` is ignored), compares them to fingerprints
stored in the target database's ``ir.config_parameter``
(``osh.module_fingerprints``) and runs ``odoo -u`` on the installed modules
that changed. The first run only records a baseline — no update is performed.

Also provides ``osh apps install`` — installing modules with ``odoo -i``
and recording their fingerprints — and ``osh apps list``, a listing of the
modules recorded in a database with their installed version and state.
The former ``osh db update``/``osh db installed`` spellings remain as
hidden deprecated aliases.

Also extends ``osh backup restore``: when a restore brings in a dump without
stored fingerprints, a local baseline is recorded right away so later
``osh apps update`` runs diff from the restore point.

The plugin's surface is declared under ``[tool.osh]`` in ``pyproject.toml``,
so the module is imported lazily — only when an ``apps`` or deprecated
``db`` subcommand, or ``osh backup restore``, runs.
"""

from .commands import (  # noqa: F401 — re-exported for discovery
    AppsInstall,
    AppsList,
    AppsUpdate,
    DbInstalled,
    DbUpdate,
)
from .core import RestoreBaseline  # noqa: F401 — re-exported for extension discovery
