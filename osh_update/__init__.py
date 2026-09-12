"""osh_update — update Odoo modules whose code changed since the last run.

Provides the ``osh update`` command: it fingerprints project modules (code
and data files; ``static/`` is ignored), compares them to fingerprints stored
in the target database's ``ir.config_parameter`` (``osh.module_fingerprints``)
and runs ``odoo -u`` on the installed modules that changed. The first run
only records a baseline — no update is performed.

Requires an osh core with ``OSH_PLUGIN_MANIFEST`` support.
"""

from .commands import update

OSH_PLUGIN_MANIFEST = {"commands": [update]}
