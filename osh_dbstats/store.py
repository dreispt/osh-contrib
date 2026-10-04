"""PostgreSQL access for ``osh db stats`` and ``osh db vacuum``.

All statements run through ``psql`` via ``osh.db.run_in_backend`` — the
same backend-routed execution osh core uses for ``db_exists`` and
friends, so Docker-backed projects run ``psql`` inside the container
automatically. Mirrors ``osh_uninstall``'s store module; plugins are
separate distributions and cannot import each other.
"""

import click
from osh.db import run_in_backend


def query(base, db_name, sql, *, variables=None, ctx=None):
    """Run *sql* and return rows as lists of fields.

    Output is ``psql -t -A`` tuples split on tabs — one field list per
    result row. Raises ``ClickException`` on error.
    """
    returncode, stdout, stderr = _psql(base, db_name, sql, variables=variables, ctx=ctx)
    if returncode != 0:
        raise click.ClickException(f"Query failed on '{db_name}': {stderr.strip()}")
    return _rows(stdout)


def query_or_none(base, db_name, sql, *, variables=None, ctx=None):
    """Like :func:`query`, but return ``None`` on error.

    Used for optional probes — ``pg_stat_statements``, ancient server
    versions — where a missing feature must degrade the report rather
    than fail it.
    """
    returncode, stdout, _ = _psql(base, db_name, sql, variables=variables, ctx=ctx)
    if returncode != 0:
        return None
    return _rows(stdout)


def run_sql(base, db_name, sql, *, ctx=None):
    """Run a statement (e.g. ``VACUUM``) and return ``(returncode, stdout, stderr)``."""
    return _psql(base, db_name, sql, ctx=ctx)


def _rows(stdout):
    """Split ``psql -t -A -F '\\t'`` output into field lists."""
    return [line.split("\t") for line in stdout.splitlines() if line]


def _psql(base, db_name, sql, *, variables=None, ctx=None):
    """Run *sql* via psql and return ``(returncode, stdout, stderr)``.

    The SQL is piped through stdin rather than ``-c`` so large statements
    cannot hit the per-argument size limit, and so *variables* — passed
    as ``psql -v key=value`` and referenced as ``:'key'`` — are quoted as
    SQL literals by psql itself, never by hand.

    ``run_in_backend`` supplies the ``PG*`` connection variables from the
    project Odoo config.
    """
    # ON_ERROR_STOP makes psql exit non-zero on SQL errors, like -c does.
    args = ["psql", "-d", db_name, "-t", "-A", "-F", "\t", "-v", "ON_ERROR_STOP=1"]
    for key, value in (variables or {}).items():
        args += ["-v", f"{key}={value}"]
    returncode, stdout, stderr = run_in_backend(ctx, base, args, input=sql)
    if returncode is None:
        raise click.ClickException("Could not locate `psql`. Is PostgreSQL installed?")
    return returncode, stdout, stderr
