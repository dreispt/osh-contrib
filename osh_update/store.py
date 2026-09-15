"""PostgreSQL-backed state for ``osh addon update``.

Module fingerprints are stored in the target database itself as an
``ir.config_parameter`` record (``osh.module_fingerprints``, a JSON
``{module: hash}`` map), so they follow the database across copies and
restores. All access goes through ``psql`` run via
``osh.db.run_in_backend`` — the same backend-routed execution core uses
for ``db_exists`` and friends, so Docker-backed projects run ``psql``
inside the container automatically.

``osh_uninstall`` carries a near-identical ``_psql`` helper: plugins
cannot import each other when loaded as user plugins, so the duplication
is deliberate. Keep the two in sync, and prefer moving the helper into
osh core if a third plugin needs it.
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
        "SELECT value FROM ir_config_parameter WHERE key = :'fp_key'",
        variables={"fp_key": FINGERPRINT_PARAM},
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
    sql = (
        "INSERT INTO ir_config_parameter (key, value) VALUES "
        "(:'fp_key', :'fp_value') "
        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
    )
    returncode, _, _ = _psql(
        base,
        db_name,
        sql,
        variables={
            "fp_key": FINGERPRINT_PARAM,
            "fp_value": json.dumps(mapping, sort_keys=True),
        },
        ctx=ctx,
    )
    if returncode != 0:
        raise click.ClickException(
            f"Could not store module fingerprints in '{db_name}'."
        )


def _psql(base, db_name, sql, *, field_separator=None, variables=None, ctx=None):
    """Run *sql* via psql and return ``(returncode, stdout, stderr)``.

    The SQL is piped through stdin rather than ``-c`` so large statements —
    such as a fingerprint UPSERT covering hundreds of modules — cannot hit
    the per-argument size limit. It must also go through stdin for the
    ``:'key'`` references below to work at all: psql interpolates
    variables only into input read from stdin or a file, never into
    ``-c``.

    *variables* are passed as ``psql -v key=value`` assignments so the
    statement can reference them as ``:'key'`` — psql quotes them as SQL
    literals using the server connection's escaping rules, so no value
    ever needs manual escaping.

    Trade-off: ``-v`` values land in the ``psql`` argv, which is
    world-readable via ``/proc/<pid>/cmdline`` while the query runs. That
    is acceptable here — fingerprints are hashes of the project's own
    code, and module names already appear in the user's own ``osh``
    command line. Do not "fix" this with ``\\set`` assignments in the
    SQL stream: psql meta-command arguments need hand-rolled backslash
    and quote escaping, reintroducing exactly the bug class ``-v``
    removes. If a value ever is sensitive, use ``\\getenv`` (psql 14+)
    with ``run_in_backend(env=...)`` instead.

    ``run_in_backend`` supplies the ``PG*`` connection variables from the
    project Odoo config.
    """
    # ON_ERROR_STOP makes psql exit non-zero on SQL errors, like -c does.
    args = ["psql", "-d", db_name, "-t", "-A", "-v", "ON_ERROR_STOP=1"]
    for key, value in (variables or {}).items():
        args += ["-v", f"{key}={value}"]
    if field_separator:
        args += ["-F", field_separator]
    returncode, stdout, stderr = run_in_backend(ctx, base, args, input=sql)
    if returncode is None:
        raise click.ClickException("Could not locate `psql`. Is PostgreSQL installed?")
    return returncode, stdout, stderr
