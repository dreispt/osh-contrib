"""``osh db stats`` and ``osh db vacuum`` handlers.

``stats`` renders a read-only dashboard collected from PostgreSQL's
statistics catalogs; ``vacuum`` runs ``VACUUM ANALYZE`` on the whole
database or on the tables the dashboard flagged as bloated.
"""

import click
from osh import echo
from osh.cli_utils import handler_command
from osh.common import find_project_root
from osh.db import db_exists, resolve_db_name_for_run, sanitize_db_name
from osh.handlers import CommandHandler

from . import render, report, store


class DbStats(CommandHandler):
    """Diagnose a database: size, bloat, indexes and live activity.

    Renders a dashboard of the PostgreSQL statistics catalogs: database
    and filestore size, largest tables, dead-tuple bloat and vacuum lag,
    unused indexes, connections and blocked/long-running queries, plus
    ``pg_stat_statements`` top queries when the extension is enabled.

    The command is read-only — use ``osh db vacuum`` to act on its
    findings.

    To enable ``pg_stat_statements`` for the QUERY STATS section, run:

    \b
      osh db shell psql -c "CREATE EXTENSION pg_stat_statements"

    If it fails, the error says what is missing:

    \b
      "must be loaded via shared_preload_libraries" — load the module at
      server start, restart PostgreSQL, then retry the CREATE EXTENSION:
      osh db shell psql -c "ALTER SYSTEM SET shared_preload_libraries = 'pg_stat_statements'"
      (append pg_stat_statements to the existing list if one is set)
    \b
      "extension is not available" — install the postgresql-contrib
      package on the database server first.

    Examples:

    \b
      osh db stats
      osh db stats -d otherdb
      osh db stats --top 20
      osh db stats --no-filestore
    """

    _cli_name = "db.stats"

    db_name = None
    top = 10
    filestore = True

    @click.option(
        "-d",
        "--db",
        "db_name",
        help="Database to inspect (default: the resolved branch database).",
    )
    @click.option(
        "--top",
        default=10,
        show_default=True,
        help="Rows shown per section.",
    )
    @click.option(
        "--filestore/--no-filestore",
        default=True,
        help="Include the filestore size in the overview "
        "(a du of the data dir — can be slow; default: on).",
    )
    def run(self):
        base = find_project_root(required=True)
        db_name = _resolve_db_name(base, self.db_name, self.ctx)
        data = report.collect(
            base,
            db_name,
            top=self.top,
            filestore=self.filestore,
            ctx=self.ctx,
        )
        click.echo(render.dashboard(data))


class DbVacuum(CommandHandler):
    """Run VACUUM ANALYZE on the database or selected tables.

    Reclaims dead-tuple space for reuse and refreshes planner statistics.
    This is the safe, non-destructive vacuum — it does not return space
    to the operating system (that would need ``VACUUM FULL`` or
    ``pg_repack``, which lock the table).

    ``osh db stats`` reports which tables need this.

    Examples:

    \b
      osh db vacuum
      osh db vacuum --table mail_message --table ir_logging
      osh db vacuum -d otherdb --dry-run
    """

    _cli_name = "db.vacuum"

    db_name = None
    tables = ()
    analyze = True
    dry_run = False

    @click.option(
        "-d",
        "--db",
        "db_name",
        help="Database to vacuum (default: the resolved branch database).",
    )
    @click.option(
        "--table",
        "tables",
        multiple=True,
        help="Vacuum only this table (repeatable).",
    )
    @click.option(
        "--analyze/--no-analyze",
        default=True,
        help="Also refresh planner statistics (default: on).",
    )
    @click.option(
        "--dry-run",
        is_flag=True,
        help="Show the VACUUM statement without executing it.",
    )
    def run(self):
        base = find_project_root(required=True)
        db_name = _resolve_db_name(base, self.db_name, self.ctx)
        tables = _validated_tables(base, db_name, self.tables, ctx=self.ctx)
        statement = _vacuum_sql(tables, analyze=self.analyze)

        if self.dry_run:
            echo.info(statement)
            return

        returncode, _, stderr = store.run_sql(base, db_name, statement, ctx=self.ctx)
        # VACUUM VERBOSE writes its progress as notices on stderr.
        if stderr.strip():
            click.echo(stderr.strip())
        if returncode != 0:
            raise click.ClickException(f"VACUUM failed on '{db_name}'.")
        target = ", ".join(tables) if tables else db_name
        echo.success(f"Vacuumed {target}. Run 'osh db stats' to see the effect.")


def _resolve_db_name(base, db_name, ctx):
    """Return the sanitized or resolved target database name."""
    name = (
        sanitize_db_name(db_name) if db_name else resolve_db_name_for_run(base, ctx=ctx)
    )
    if not db_exists(base, name, ctx=ctx):
        raise click.ClickException(f"Database '{name}' does not exist.")
    return name


def _validated_tables(base, db_name, tables, ctx=None):
    """Check *tables* against ``pg_stat_user_tables`` and return the list."""
    if not tables:
        return []
    # ``pg_class`` rather than ``pg_stat_user_tables``: a table with no
    # statistics entry yet (never analyzed or modified) must still be
    # accepted for vacuuming.
    known = {
        row[0]
        for row in store.query(
            base,
            db_name,
            "SELECT c.relname FROM pg_class c"
            " JOIN pg_namespace n ON n.oid = c.relnamespace"
            " WHERE c.relkind = 'r'"
            " AND n.nspname NOT IN ('pg_catalog', 'information_schema')"
            " AND n.nspname NOT LIKE 'pg_toast%'"
            " AND n.nspname NOT LIKE 'pg_temp_%'",
            ctx=ctx,
        )
    }
    bad = [t for t in tables if t not in known]
    if bad:
        raise click.ClickException(
            "Unknown table(s): " + ", ".join(bad) + ". See 'osh db stats'."
        )
    return list(tables)


def _vacuum_sql(tables, *, analyze):
    """Build the ``VACUUM`` statement for *tables*.

    Table names are validated against the catalog before reaching this
    point; identifiers are still quoted defensively.
    """
    options = "VERBOSE, ANALYZE" if analyze else "VERBOSE"
    statement = f"VACUUM ({options})"
    if tables:
        quoted = ", ".join('"' + t.replace('"', '""') + '"' for t in tables)
        statement += f" {quoted}"
    return statement


#: Standalone commands — used by tests; the CLI wires the same handlers
#: through the ``[group_commands.db]`` declaration.
stats = handler_command("stats", DbStats)
vacuum = handler_command("vacuum", DbVacuum)
