"""PostgreSQL-backed state for ``osh addon uninstall``.

Module states and dependency relations are read directly from the target
database through ``psql`` run via ``osh.db.run_in_backend`` — the same
backend-routed execution osh core uses for ``db_exists`` and friends, so
Docker-backed projects run ``psql`` inside the container automatically.
This mirrors ``osh_update``'s store module; plugins cannot import each
other when loaded as user plugins.
"""

import click
from osh.db import run_in_backend

# Module states in which ``button_uninstall`` accepts the module.
REMOVABLE_STATES = ("installed", "to upgrade")

# States ``downstream_dependencies`` never cascades into — dependents in
# these states are neither marked ``to remove`` nor traversed further.
DEAD_STATES = ("uninstalled", "uninstallable", "to remove")


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
    states = {}
    for line in stdout.splitlines():
        name, _, state = line.partition("\t")
        if name:
            states[name] = state
    return states


def get_removal_set(base, db_name, names, ctx=None):
    """Return the sorted module set ``button_uninstall`` would mark to remove.

    Mirrors ``ir.module.module.downstream_dependencies`` — the named modules
    plus every module depending on them, transitively — skipping modules in
    ``DEAD_STATES``, exactly like the ORM. Advisory only: the authoritative
    removal set is computed by the ORM at uninstall time.
    """
    quoted = ", ".join(f"'{_sql_literal(n)}'" for n in names)
    dead = ", ".join(f"'{s}'" for s in DEAD_STATES)
    sql = (
        "WITH RECURSIVE dep(id) AS ("
        f"SELECT id FROM ir_module_module WHERE name IN ({quoted}) "
        "UNION "
        "SELECT d.module_id "
        "FROM dep "
        "JOIN ir_module_module dm ON dm.id = dep.id "
        "JOIN ir_module_module_dependency d ON d.name = dm.name "
        "JOIN ir_module_module m2 ON m2.id = d.module_id "
        f"WHERE m2.state NOT IN ({dead})"
        ") "
        "SELECT DISTINCT m.name "
        "FROM ir_module_module m JOIN dep ON m.id = dep.id "
        "ORDER BY m.name"
    )
    returncode, stdout, stderr = _psql(base, db_name, sql, ctx=ctx)
    if returncode != 0:
        raise click.ClickException(
            f"Could not read module dependencies from '{db_name}': " f"{stderr.strip()}"
        )
    return [n for n in stdout.splitlines() if n]


def _psql(base, db_name, sql, *, field_separator=None, ctx=None):
    """Run *sql* via psql and return ``(returncode, stdout, stderr)``.

    The SQL is piped through stdin rather than ``-c`` so large statements
    cannot hit the per-argument size limit. ``run_in_backend`` supplies the
    ``PG*`` connection variables from the project Odoo config.
    """
    # ON_ERROR_STOP makes psql exit non-zero on SQL errors, like -c does.
    args = ["psql", "-d", db_name, "-t", "-A", "-v", "ON_ERROR_STOP=1"]
    if field_separator:
        args += ["-F", field_separator]
    returncode, stdout, stderr = run_in_backend(ctx, base, args, input=sql)
    if returncode is None:
        raise click.ClickException("Could not locate `psql`. Is PostgreSQL installed?")
    return returncode, stdout, stderr


def _sql_literal(value):
    """Escape *value* for use as a single-quoted SQL literal."""
    return str(value).replace("'", "''")
