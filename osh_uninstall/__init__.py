"""osh_uninstall — uninstall Odoo modules from a database.

Provides the ``osh addon uninstall`` command: it validates the requested
comma-separated module list against the target database's
``ir_module_module`` table, previews the dependent modules that will also
be removed, asks for confirmation, and performs the removal by piping a
``button_immediate_uninstall`` call into ``osh odoo shell``. Module states
are re-checked afterwards so a silently swallowed failure never reports
success.

Requires osh >= 0.8, which provides the ``addon`` command group this
plugin attaches to. On an older core the plugin still loads but the
command never appears; check with ``osh addon --help``.
"""

from .commands import uninstall

OSH_PLUGIN_MANIFEST = {"group_commands": {"addon": [uninstall]}}
