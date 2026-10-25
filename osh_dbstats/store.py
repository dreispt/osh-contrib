"""PostgreSQL access for ``osh db stats`` and ``osh db vacuum``.

All statements run through ``psql`` via ``osh.db.run_in_runtime`` — the
same execution core osh routes through the active runtime for
``db_exists`` and friends, so Docker-backed projects run ``psql`` inside the container
automatically. Mirrors ``osh_uninstall``'s store module; plugins are
separate distributions and cannot import each other.
"""

import click
from osh.db import psql, psql_rows, run_in_runtime


def query(base, db_name, sql, *, variables=None, ctx=None):
    """Run *sql* and return rows as lists of fields.

    Output is ``psql -t -A`` tuples split on tabs — one field list per
    result row. Raises ``ClickException`` on error.
    """
    returncode, rows, stderr = psql_rows(base, db_name, sql, field_separator="\t", variables=variables, ctx=ctx)
    if returncode != 0:
        raise click.ClickException(f"Query failed on '{db_name}': {stderr.strip()}")
    return rows


def query_or_none(base, db_name, sql, *, variables=None, ctx=None):
    """Like :func:`query`, but return ``None`` on error.

    Used for optional probes — ``pg_stat_statements``, ancient server
    versions — where a missing feature must degrade the report rather
    than fail it.
    """
    returncode, rows, _ = psql_rows(base, db_name, sql, field_separator="\t", variables=variables, ctx=ctx)
    if returncode != 0:
        return None
    return rows


def run_sql(base, db_name, sql, *, ctx=None):
    """Run a statement (e.g. ``VACUUM``) and return ``(returncode, stdout, stderr)``."""
    return psql(base, db_name, sql, field_separator="\t", ctx=ctx)



