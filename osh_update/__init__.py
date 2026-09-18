"""osh_update — update Odoo modules whose code changed since the last run.

Provides the ``osh addon update`` command: it fingerprints project modules
(code and data files; ``static/`` is ignored), compares them to fingerprints
stored in the target database's ``ir.config_parameter``
(``osh.module_fingerprints``) and runs ``odoo -u`` on the installed modules
that changed. The first run only records a baseline — no update is performed.

Also extends ``osh db restore``: when a restore brings in a dump without
stored fingerprints, a local baseline is recorded right away so later
``osh addon update`` runs diff from the restore point.

Requires osh >= 0.8, which provides the ``addon`` command group this
plugin attaches to. On an older core the plugin still loads but the
command never appears; check with ``osh addon --help``.
"""

from .commands import update
from .core import RestoreBaseline  # noqa: F401 — registers the db.restore extension

OSH_PLUGIN_MANIFEST = {
    "group_commands": {"addon": [update]},
}
