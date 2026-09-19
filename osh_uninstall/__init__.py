"""osh_uninstall — uninstall Odoo modules from a database.

Provides the ``osh addon uninstall`` command: it validates the requested
comma-separated module list against the target database's
``ir_module_module`` table, previews the dependent modules that will also
be removed, asks for confirmation, and performs the removal by piping a
``button_immediate_uninstall`` call into ``osh odoo shell``. Module states
are re-checked afterwards so a silently swallowed failure never reports
success.

The command is declared in ``osh-plugin.toml``, so the module is imported
lazily — only when ``osh addon uninstall`` actually runs.
"""

from .commands import AddonUninstall  # noqa: F401 — re-exported for discovery
