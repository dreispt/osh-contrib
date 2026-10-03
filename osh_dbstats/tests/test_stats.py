"""Tests for the ``osh db stats`` and ``osh db vacuum`` commands."""

import time

from click.testing import CliRunner

from osh_dbstats.commands import stats, vacuum


def _wait_stats(pg_db, db_name, condition, timeout=10):
    """Poll *condition* until the stats collector reports it true.

    ``pg_stat_*`` counters lag the committing transactions slightly, so
    assertions on them must wait for the collector to catch up.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pg_db.query(db_name, condition) == "t":
            return
        time.sleep(0.2)
    raise AssertionError(f"stats did not settle: {condition}")


def test_stats_renders_dashboard(in_project, pg_db):
    """An Odoo database gets the full dashboard with its version."""
    db_name = pg_db.make_odoo_db()
    pg_db.make_table(db_name, "mail_message", 2000)
    _wait_stats(
        pg_db,
        db_name,
        "SELECT n_live_tup >= 2000 FROM pg_stat_user_tables"
        " WHERE relname = 'mail_message'",
    )

    result = CliRunner().invoke(stats, ["-d", db_name, "--no-filestore"])

    assert result.exit_code == 0
    for section in (
        "DATABASE",
        "LARGEST TABLES",
        "TABLE HEALTH",
        "INDEXES",
        "ACTIVITY",
        "QUERY STATS",
    ):
        assert section in result.output
    assert "Odoo 17.0" in result.output
    assert "mail_message" in result.output


def test_stats_plain_database(in_project, pg_db):
    """A non-Odoo database gets the generic dashboard without the watchlist."""
    db_name = pg_db.create()
    pg_db.make_table(db_name, "data", 100)

    result = CliRunner().invoke(stats, ["-d", db_name, "--no-filestore"])

    assert result.exit_code == 0
    assert "not an Odoo database" in result.output
    assert "data" in result.output


def test_stats_top_limits_sections(in_project, pg_db):
    """--top caps each 'top' section to the requested number of rows."""
    db_name = pg_db.create()
    for i in range(3):
        pg_db.make_table(db_name, f"t{i}", 100 * (i + 1))

    result = CliRunner().invoke(stats, ["-d", db_name, "--no-filestore", "--top", "1"])

    assert result.exit_code == 0
    assert "t2" in result.output
    assert "t0" not in result.output
    assert "t1" not in result.output


def test_stats_pg_stat_statements_handled(in_project, pg_db):
    """The query stats section adapts to pg_stat_statements availability."""
    db_name = pg_db.create()
    enabled = (
        pg_db.query(
            db_name,
            "SELECT EXISTS (SELECT 1 FROM pg_extension"
            " WHERE extname = 'pg_stat_statements')",
        )
        == "t"
    )

    result = CliRunner().invoke(stats, ["-d", db_name, "--no-filestore"])

    assert result.exit_code == 0
    if enabled:
        assert "pg_stat_statements is not enabled" not in result.output
    else:
        assert "pg_stat_statements is not enabled" in result.output
        assert "osh db stats --help" in result.output


def test_stats_flags_bloated_table(in_project, pg_db):
    """A table with many dead tuples is flagged in TABLE HEALTH."""
    db_name = pg_db.create()
    pg_db.make_table(db_name, "bloated", 3000)
    pg_db.psql(db_name, "DELETE FROM bloated WHERE id > 1800")
    pg_db.psql(db_name, "ANALYZE bloated")
    _wait_stats(
        pg_db,
        db_name,
        "SELECT n_dead_tup >= 1200 FROM pg_stat_user_tables"
        " WHERE relname = 'bloated'",
    )

    result = CliRunner().invoke(stats, ["-d", db_name, "--no-filestore"])

    assert result.exit_code == 0
    assert "no tables need vacuum" not in result.output
    assert "bloated" in result.output
    assert "40% dead" in result.output


def test_stats_missing_database(in_project, pg_db):
    """Asking for a database that does not exist fails cleanly."""
    result = CliRunner().invoke(stats, ["-d", "osh-test-nonexistent-db"])

    assert result.exit_code != 0
    assert "does not exist" in result.output


def test_vacuum_marks_table_vacuumed(in_project, pg_db):
    """Vacuuming a table sets its last_vacuum timestamp."""
    db_name = pg_db.create()
    pg_db.make_table(db_name, "t1", 100)
    pg_db.make_table(db_name, "t2", 100)

    result = CliRunner().invoke(vacuum, ["-d", db_name, "--table", "t1"])

    assert result.exit_code == 0
    assert "Vacuumed t1" in result.output
    _wait_stats(
        pg_db,
        db_name,
        "SELECT last_vacuum IS NOT NULL FROM pg_stat_user_tables"
        " WHERE relname = 't1'",
    )
    assert (
        pg_db.query(
            db_name,
            "SELECT last_vacuum IS NULL FROM pg_stat_user_tables"
            " WHERE relname = 't2'",
        )
        == "t"
    )


def test_vacuum_whole_database(in_project, pg_db):
    """Without --table, the whole database is vacuumed."""
    db_name = pg_db.create()
    pg_db.make_table(db_name, "t1", 100)
    pg_db.make_table(db_name, "t2", 100)

    result = CliRunner().invoke(vacuum, ["-d", db_name])

    assert result.exit_code == 0
    assert "Vacuumed" in result.output
    _wait_stats(
        pg_db,
        db_name,
        "SELECT count(*) = 2 FROM pg_stat_user_tables"
        " WHERE relname IN ('t1', 't2') AND last_vacuum IS NOT NULL",
    )


def test_vacuum_unknown_table_fails(in_project, pg_db):
    """A typo'd table name is rejected before touching the database."""
    db_name = pg_db.create()

    result = CliRunner().invoke(vacuum, ["-d", db_name, "--table", "nope"])

    assert result.exit_code != 0
    assert "Unknown table(s): nope" in result.output


def test_vacuum_dry_run(in_project, pg_db):
    """--dry-run shows the statement and changes nothing."""
    db_name = pg_db.create()
    pg_db.make_table(db_name, "t1", 100)

    result = CliRunner().invoke(vacuum, ["-d", db_name, "--table", "t1", "--dry-run"])

    assert result.exit_code == 0
    assert 'VACUUM (VERBOSE, ANALYZE) "t1"' in result.output
    assert (
        pg_db.query(
            db_name,
            "SELECT last_vacuum IS NULL FROM pg_stat_user_tables"
            " WHERE relname = 't1'",
        )
        == "t"
    )
