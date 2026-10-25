"""PostgreSQL-backed state for ``osh apps uninstall``.

Module states and dependency relations are read directly from the target
database through ``psql`` run via ``osh.db.run_in_runtime`` — the same
execution core osh routes through the active runtime for ``db_exists``
and friends, so
Docker-backed projects run ``psql`` inside the container automatically.
This mirrors ``osh_update``'s store module; plugins are separate
distributions and cannot import each other.
"""

import click
from osh.db import psql, run_in_runtime

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
    returncode, stdout, stderr = psql(
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
    names = list(names)
    if not names:
        return []
    # Names go through psql variables (:'mod0', ...) so psql performs
    # server-aware literal quoting — no manual escaping into the SQL text.
    quoted = ", ".join(f":'mod{i}'" for i in range(len(names)))
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
    returncode, stdout, stderr = psql(
        base,
        db_name,
        sql,
        variables={f"mod{i}": name for i, name in enumerate(names)},
        ctx=ctx,
    )
    if returncode != 0:
        raise click.ClickException(
            f"Could not read module dependencies from '{db_name}': " f"{stderr.strip()}"
        )
    return [n for n in stdout.splitlines() if n]


