"""osh_uninstall — uninstall Odoo modules from a database.

Provides the ``osh uninstall`` command: it validates the requested
comma-separated module list against the target database's
``ir_module_module`` table, previews the dependent modules that will also
be removed, asks for confirmation, and performs the removal by piping a
``button_immediate_uninstall`` call into ``osh odoo shell``. Module states
are re-checked afterwards so a silently swallowed failure never reports
success.

Requires an osh core with ``OSH_PLUGIN_MANIFEST`` support.
"""

from .commands import uninstall

OSH_PLUGIN_MANIFEST = {"commands": [uninstall]}
