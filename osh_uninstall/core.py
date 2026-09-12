"""Uninstall orchestration for ``osh uninstall``.

Runs the removal through ``osh odoo shell``, piping a small script into
``odoo shell``'s stdin — when stdin is not a tty, Odoo executes it with a
superuser ``env`` instead of opening a REPL. Kept separate from the Click
command so it can be monkeypatched in tests.
"""

import json
import subprocess
import sys


def uninstall_script(modules):
    """Return the Python snippet executed inside ``odoo shell``."""
    names = json.dumps(sorted(modules))
    return (
        "mods = env['ir.module.module'].search("
        f"[('name', 'in', {names})])\n"
        "mods.button_immediate_uninstall()\n"
    )


def run_uninstall(modules, db_name, *, dry_run=False):
    """Run ``osh odoo shell -d <db>`` executing the uninstall script.

    ``osh odoo`` exec's ``odoo-bin``, so the subprocess return code is
    Odoo's own exit code.
    """
    cmd = [sys.executable, "-m", "osh", "odoo"]
    if dry_run:
        cmd += ["--dry-run"]
    cmd += ["shell", "-d", db_name]
    return subprocess.run(cmd, input=uninstall_script(modules), text=True).returncode
