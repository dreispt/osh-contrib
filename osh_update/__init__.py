"""osh_update — update Odoo modules whose code changed since the last run.

Provides the ``osh addon update`` command: it fingerprints project modules
(code and data files; ``static/`` is ignored), compares them to fingerprints
stored in the target database's ``ir.config_parameter``
(``osh.module_fingerprints``) and runs ``odoo -u`` on the installed modules
that changed. The first run only records a baseline — no update is performed.

Also extends ``osh db restore``: when a restore brings in a dump without
stored fingerprints, a local baseline is recorded right away so later
``osh addon update`` runs diff from the restore point.

The plugin's surface is declared in ``osh-plugin.toml``, so the module is
imported lazily — only when ``osh addon update`` or ``osh db restore`` runs.
"""

from .commands import AddonUpdate  # noqa: F401 — re-exported for discovery
from .core import RestoreBaseline  # noqa: F401 — re-exported for extension discovery
