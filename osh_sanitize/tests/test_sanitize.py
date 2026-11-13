"""Tests for ``osh db sanitize`` and the ``backup restore`` extension."""

from click.testing import CliRunner
from osh.cli_utils import handler_command

from osh_sanitize.commands import DbSanitize
from osh_sanitize.restore import RestoreSanitize

sanitize = handler_command("sanitize", DbSanitize)


def test_sanitize_list_shows_resolved_scripts(in_project):
    """``osh db sanitize --list`` shows the bundled anonymize profile."""
    result = CliRunner().invoke(sanitize, ["--list"])

    assert result.exit_code == 0, result.output
    assert "anonymize:" in result.output
    assert "010_identity.sql  (bundled)" in result.output


def test_sanitize_missing_database_errors(in_project, pg_db):
    """Sanitizing a database that does not exist is an error."""
    result = CliRunner().invoke(sanitize, ["-d", pg_db.name(), "--force"])

    assert result.exit_code != 0
    assert "does not exist" in result.output


def test_sanitize_dry_run_previews_scripts_and_trim(in_project, pg_db):
    """``--dry-run`` names the scripts without writing anything."""
    name = pg_db.create()
    result = CliRunner().invoke(sanitize, ["-d", name, "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "Would run anonymize script: 010_identity.sql (bundled)" in result.output


def test_sanitize_force_runs_on_real_database(in_project, pg_db):
    """A full run on an empty database: guarded scripts no-op, absent tables skip."""
    name = pg_db.create()
    result = CliRunner().invoke(sanitize, ["-d", name, "--force"])

    assert result.exit_code == 0, result.output
    assert "Running anonymize script: 010_identity.sql" in result.output
    assert "Running trim script: 080_mail_message.sql" in result.output
    assert "Database size:" in result.output
    assert "reclaimed" in result.output


def test_sanitize_warns_and_confirms_on_unneutralized_db(in_project, pg_db):
    """Without ``--force``, an unneutralized database warns and asks."""
    name = pg_db.create()
    result = CliRunner().invoke(sanitize, ["-d", name], input="n\n")

    assert result.exit_code != 0
    assert "does not look neutralized" in result.output


def test_sanitize_step_argument_selects_groups(in_project, pg_db):
    """`osh db sanitize trim` runs only the trim group."""
    name = pg_db.create()
    result = CliRunner().invoke(sanitize, ["-d", name, "trim", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "anonymize script" not in result.output
    assert "Would run trim script: 010_ir_logging.sql" in result.output


def test_sanitize_step_argument_rejects_unknown(in_project):
    """An unknown group name is a usage error."""
    result = CliRunner().invoke(sanitize, ["bogus"])

    assert result.exit_code != 0
    assert "Unknown group(s): bogus" in result.output


def test_sanitize_identity_group_runs_only_identity_level(in_project, pg_db):
    """`osh db sanitize identity` runs only the identity anonymize level."""
    name = pg_db.create()
    result = CliRunner().invoke(sanitize, ["-d", name, "identity", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "Would run anonymize script: 010_identity.sql" in result.output
    assert "050_address.sql" not in result.output
    assert "trim script" not in result.output


def test_sanitize_address_level_does_not_mark_anonymized(in_project, pg_db):
    """A single level leaves out the ``database.is_anonymized`` marker."""
    name = pg_db.create()
    result = CliRunner().invoke(sanitize, ["-d", name, "address", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "Would run anonymize script: 050_address.sql" in result.output
    assert "is_anonymized" not in result.output


def test_sanitize_skip_does_not_mark_anonymized(in_project, pg_db):
    """Skipping an anonymize script leaves out the anonymized marker."""
    name = pg_db.create()
    result = CliRunner().invoke(
        sanitize, ["-d", name, "anonymize", "--skip", "address", "--dry-run"]
    )

    assert result.exit_code == 0, result.output
    assert "Would run anonymize script: 010_identity.sql" in result.output
    assert "is_anonymized" not in result.output


def test_sanitize_anonymize_group_runs_every_level(in_project, pg_db):
    """`osh db sanitize anonymize identity` still runs the whole group."""
    name = pg_db.create()
    result = CliRunner().invoke(
        sanitize, ["-d", name, "anonymize", "identity", "--dry-run"]
    )

    assert result.exit_code == 0, result.output
    assert "050_address.sql" in result.output
    assert "090_anonymized.sql" in result.output


def test_sanitize_rejects_negative_keep_days(in_project, pg_db):
    """A negative retention would delete recent rows — it is an error."""
    name = pg_db.create()
    result = CliRunner().invoke(sanitize, ["-d", name, "--keep-days", "-1", "--force"])

    assert result.exit_code != 0
    assert "keep_days must not be negative" in result.output
    assert "anonymize script" not in result.output


def test_sanitize_dry_run_does_not_vacuum(in_project, pg_db):
    """``--dry-run --vacuum`` previews without vacuuming."""
    name = pg_db.create()
    pg_db.make_table(name, "ir_logging", 1)
    result = CliRunner().invoke(sanitize, ["-d", name, "trim", "--vacuum", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "Vacuuming" not in result.output


def test_sanitize_trim_keeps_pending_jobs_and_notifications(in_project, pg_db):
    """Trim keeps unprocessed queue jobs and notifications of deleted mails."""
    name = pg_db.create()
    pg_db.psql(
        name,
        "CREATE TABLE queue_job (id serial PRIMARY KEY, state varchar);"
        "INSERT INTO queue_job (state) VALUES ('done'), ('cancelled'), "
        "('pending'), ('failed');"
        "CREATE TABLE mail_mail (id serial PRIMARY KEY);"
        "INSERT INTO mail_mail DEFAULT VALUES;"
        "CREATE TABLE mail_notification (id serial PRIMARY KEY, "
        "mail_mail_id int REFERENCES mail_mail ON DELETE SET NULL);"
        "INSERT INTO mail_notification (mail_mail_id) SELECT id FROM mail_mail;",
    )
    result = CliRunner().invoke(sanitize, ["-d", name, "trim", "--force"])

    assert result.exit_code == 0, result.output
    jobs = pg_db.query(name, "SELECT state FROM queue_job ORDER BY id")
    assert jobs.split() == ["pending", "failed"]
    assert pg_db.query(name, "SELECT count(*) FROM mail_mail") == "0"
    assert pg_db.query(name, "SELECT count(*) FROM mail_notification") == "1"


def _bare_restore(monkeypatch, **attrs):
    """A ``RestoreSanitize`` instance with params set, no Click context."""
    handler = RestoreSanitize.__new__(RestoreSanitize)
    handler.env = None
    handler.db_name = "db"
    handler.dry_run = False
    for key, value in attrs.items():
        setattr(handler, key, value)
    return handler


def test_restore_extension_adds_sanitize_options():
    """``backup restore`` gains --anonymize/--trim/--keep-days."""
    names = {param.name for param in RestoreSanitize.get_options()}

    assert {"anonymize", "trim", "keep_days"} <= names


def test_restore_sanitize_delegates_to_db_sanitize(monkeypatch):
    """--anonymize/--trim run the sanitize handler with force carried over."""
    calls = []

    class StubSanitize:
        def __init__(self, env=None, **params):
            calls.append(params)

        def run(self):
            pass

    monkeypatch.setattr("osh_sanitize.restore.DbSanitize", StubSanitize)
    handler = _bare_restore(monkeypatch, anonymize=True, trim=True, keep_days=7)
    handler.post_restore()

    assert calls == [
        {
            "database": "db",
            "no_anonymize": False,
            "no_trim": False,
            "keep_days": 7,
            "force": True,
        }
    ]


def test_restore_sanitize_skips_without_flags(monkeypatch):
    """A plain restore never touches the sanitize handler."""
    monkeypatch.setattr(
        "osh_sanitize.restore.DbSanitize",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("sanitize ran")),
    )
    handler = _bare_restore(monkeypatch, anonymize=False, trim=False)
    handler.post_restore()
