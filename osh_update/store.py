"""PostgreSQL-backed state for ``osh addon update``.

Module fingerprints are stored in the target database itself as an
``ir.config_parameter`` record (``osh.module_fingerprints``, a JSON
``{module: hash}`` map), so they follow the database across copies and
restores. All access goes through ``psql`` run via
``osh.db.run_in_backend`` — the same backend-routed execution core uses
for ``db_exists`` and friends, so Docker-backed projects run ``psql``
inside the container automatically.
"""

import json

import click
from osh import echo
from osh.db import run_in_backend

FINGERPRINT_PARAM = "osh.module_fingerprints"

# Module states in which a ``-u`` update is meaningful: ``to install``
# modules get fresh code at install time anyway, and ``-u`` on a
# ``to remove`` module would cancel the pending uninstall.
ACTIVE_STATES = ("installed", "to upgrade")


def get_module_states(base, db_name, ctx=None):
    """Return ``{name: state}`` from ``ir_module_module``.

    Returns ``None`` when the table does not exist — the database is not
    an initialized Odoo database.
    """
    returncode, stdout, stderr = _psql(
        base,
        db_name,
        "SELECT name, state FROM ir_module_module",
        field_separator="\t",
        ctx=ctx,
    )
    if returncode != 0:
        if 'relation "ir_module_module" does not exist' in stderr:
            return None
        raise click.ClickException(
            f"Could not read module states from '{db_name}': " f"{stderr.strip()}"
        )
    return dict(line.split("\t", 1) for line in stdout.splitlines() if "\t" in line)


def read_fingerprints(base, db_name, ctx=None):
    """Return the stored ``{module: hash}`` map, or None when never recorded."""
    returncode, stdout, _ = _psql(
        base,
        db_name,
        "SELECT value FROM ir_config_parameter " f"WHERE key = '{FINGERPRINT_PARAM}'",
        ctx=ctx,
    )
    if returncode != 0:
        raise click.ClickException(
            f"Could not read module fingerprints from '{db_name}'."
        )
    value = stdout.strip()
    if not value:
        return None
    try:
        data = json.loads(value)
    except ValueError:
        data = None
    if not isinstance(data, dict):
        echo.warning(
            f"Existing '{FINGERPRINT_PARAM}' value in '{db_name}' is not "
            "a JSON object; a new baseline will be recorded."
        )
        return None
    return data


def write_fingerprints(base, db_name, mapping, ctx=None):
    """Store *mapping* as the ``osh.module_fingerprints`` config parameter."""
    payload = json.dumps(mapping, sort_keys=True).replace("'", "''")
    sql = (
        "INSERT INTO ir_config_parameter (key, value) VALUES "
        f"('{FINGERPRINT_PARAM}', '{payload}') "
        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
    )
    returncode, _, _ = _psql(base, db_name, sql, ctx=ctx)
    if returncode != 0:
        raise click.ClickException(
            f"Could not store module fingerprints in '{db_name}'."
        )


def _psql(base, db_name, sql, *, field_separator=None, ctx=None):
    """Run *sql* via psql and return ``(returncode, stdout, stderr)``.

    The SQL is piped through stdin rather than ``-c`` so large statements —
    such as a fingerprint UPSERT covering hundreds of modules — cannot hit
    the per-argument size limit. ``run_in_backend`` supplies the ``PG*``
    connection variables from the project Odoo config.
    """
    # ON_ERROR_STOP makes psql exit non-zero on SQL errors, like -c does.
    args = ["psql", "-d", db_name, "-t", "-A", "-v", "ON_ERROR_STOP=1"]
    if field_separator:
        args += ["-F", field_separator]
    returncode, stdout, stderr = run_in_backend(ctx, base, args, input=sql)
    if returncode is None:
        raise click.ClickException("Could not locate `psql`. Is PostgreSQL installed?")
    return returncode, stdout, stderr
