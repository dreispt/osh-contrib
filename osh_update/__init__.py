"""osh_update — update Odoo modules whose code changed since the last run.

Provides the ``osh addon update`` command: it fingerprints project modules
(code and data files; ``static/`` is ignored), compares them to fingerprints
stored in the target database's ``ir.config_parameter``
(``osh.module_fingerprints``) and runs ``odoo -u`` on the installed modules
that changed. The first run only records a baseline — no update is performed.

Also subscribes to the ``osh_db_get.post_restore`` hook point (osh >= 0.9):
when ``osh db restore`` brings in a dump without stored fingerprints, a
local baseline is recorded right away so later ``osh addon update`` runs
diff from the restore point.

Requires osh >= 0.8, which provides the ``addon`` command group this
plugin attaches to. On an older core the plugin still loads but the
command never appears; check with ``osh addon --help``.
"""

from .commands import update
from .core import post_restore

OSH_PLUGIN_MANIFEST = {
    "group_commands": {"addon": [update]},
    "hooks": {"osh_db_get.post_restore": [post_restore]},
}
