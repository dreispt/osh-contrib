"""Regression tests for ``osh db sanitize`` issues found in review.

Each test encodes a user-facing bug as a story: sanitizing must mask
every stored identity field coherently, never abort on login swaps,
stay atomic per script, honor ``keep_days = 0``, select
``--script``/``--skip`` across both script groups, reject unknown names
before running anything, and actually return trimmed space to disk.
"""

import json

from click.testing import CliRunner
from osh.cli_utils import handler_command

from osh_sanitize.commands import DbSanitize

sanitize = handler_command("sanitize", DbSanitize)


def test_partner_stored_identity_fields_are_masked(in_project, pg_db):
    """Every stored identity column on res_partner is rewritten, coherently.

    As a user sanitizing a dump for a colleague, I expect no trace of the
    original contact — but ``osh db sanitize identity`` only masked
    ``name``/``email``/``phone``, leaving ``complete_name``,
    ``display_name``, ``email_normalized``, ``phone_sanitized``,
    ``company_name`` and ``commercial_company_name`` with 'Jane Doe' and
    'Acme Corp'. Derived fields must also stay coherent: the contact's
    ``complete_name`` follows the parent's placeholder name and
    ``email_normalized`` matches the new ``email``.
    """
    name = pg_db.create()
    pg_db.psql(
        name,
        "CREATE TABLE res_partner ("
        "id serial PRIMARY KEY, name varchar, complete_name varchar, "
        "display_name varchar, email varchar, email_normalized varchar, "
        "phone varchar, phone_sanitized varchar, is_company boolean, "
        "parent_id int, commercial_partner_id int, company_name varchar, "
        "commercial_company_name varchar);"
        "INSERT INTO res_partner (id, name, complete_name, display_name, "
        "email, email_normalized, phone, phone_sanitized, is_company, "
        "parent_id, commercial_partner_id, company_name, "
        "commercial_company_name) VALUES "
        "(1, 'Acme Corp', 'Acme Corp', 'Acme Corp', NULL, NULL, NULL, NULL, "
        "true, NULL, 1, 'Acme Corp', 'Acme Corp'),"
        "(2, 'Jane Doe', 'Acme Corp, Jane Doe', 'Acme Corp, Jane Doe', "
        "'Jane.Doe@Acme.com', 'jane.doe@acme.com', '+1 555 0100', "
        "'+15550100', false, 1, 1, NULL, 'Acme Corp');",
    )
    result = CliRunner().invoke(sanitize, ["--db", name, "identity", "--force"])

    assert result.exit_code == 0, result.output
    dump = pg_db.query(name, "SELECT row_to_json(p) FROM res_partner p ORDER BY id")
    for leaked in ("Jane", "jane", "Acme", "acme.com", "5550100", "555 0100"):
        assert leaked not in dump, f"{leaked!r} survived sanitizing:\n{dump}"
    rows = [json.loads(line) for line in dump.splitlines()]
    contact = next(row for row in rows if row["id"] == 2)
    assert contact["complete_name"] == "Partner 1, Partner 2"
    assert contact["email_normalized"] == contact["email"]


def test_bank_account_derived_fields_are_masked(in_project, pg_db):
    """Derived bank columns on res_partner_bank are rewritten too.

    ``osh db sanitize identity`` masked ``acc_number`` but left
    ``sanitized_acc_number`` — the digits actually used for matching —
    and ``acc_holder_name`` untouched, so the account number and holder
    name survived in the sanitized database.
    """
    name = pg_db.create()
    pg_db.psql(
        name,
        "CREATE TABLE res_partner_bank ("
        "id serial PRIMARY KEY, acc_number varchar, "
        "sanitized_acc_number varchar, acc_holder_name varchar);"
        "INSERT INTO res_partner_bank "
        "(acc_number, sanitized_acc_number, acc_holder_name) VALUES "
        "('BE68 5390 0754 7034', 'BE68539007547034', 'Jane Doe');",
    )
    result = CliRunner().invoke(sanitize, ["--db", name, "identity", "--force"])

    assert result.exit_code == 0, result.output
    dump = pg_db.query(name, "SELECT row_to_json(b) FROM res_partner_bank b")
    for leaked in ("539007547034", "5390 0754", "Jane", "BE68"):
        assert leaked not in dump, f"{leaked!r} survived sanitizing:\n{dump}"


def test_recent_tracking_values_are_masked(in_project, pg_db):
    """Field-history values on recent mail_tracking_value rows are masked.

    The trim retention keeps the last 30 days of ``mail_tracking_value``
    rows, so a default ``osh db sanitize`` run keeps the row — but the
    anonymize step never touched its ``old_value_*``/``new_value_*``
    columns, leaving names, emails and phones in the sanitized dump.
    """
    name = pg_db.create()
    pg_db.psql(
        name,
        "CREATE TABLE mail_tracking_value ("
        "id serial PRIMARY KEY, create_date timestamp DEFAULT now(), "
        "old_value_char varchar, new_value_char varchar, "
        "old_value_text text, new_value_text text);"
        "INSERT INTO mail_tracking_value "
        "(old_value_char, new_value_char, old_value_text, new_value_text) "
        "VALUES ('Jane Doe', 'Jane Smith', 'jane@acme.com', '+1 555 0100');",
    )
    result = CliRunner().invoke(sanitize, ["--db", name, "--force"])

    assert result.exit_code == 0, result.output
    assert pg_db.query(name, "SELECT count(*) FROM mail_tracking_value") == "1"
    dump = pg_db.query(name, "SELECT row_to_json(t) FROM mail_tracking_value t")
    for leaked in ("Jane", "jane@acme.com", "555 0100"):
        assert leaked not in dump, f"{leaked!r} survived sanitizing:\n{dump}"


def test_employee_identity_is_masked_in_resource_and_hr_fields(in_project, pg_db):
    """Employee PII is masked in hr_employee and its resource_resource.

    ``osh db sanitize identity`` rewrote ``hr_employee.name`` but left
    the national identifiers, spouse name, permit/visa numbers, work
    coordinates and ``resource_resource.name`` — the resource kept
    displaying the employee's real name.
    """
    name = pg_db.create()
    pg_db.psql(
        name,
        "CREATE TABLE resource_resource (id serial PRIMARY KEY, name varchar);"
        "CREATE TABLE hr_employee ("
        "id serial PRIMARY KEY, name varchar, resource_id int, "
        "ssnid varchar, sinid varchar, spouse_complete_name varchar, "
        "permit_no varchar, visa_no varchar, work_email varchar, "
        "work_phone varchar, mobile_phone varchar);"
        "INSERT INTO resource_resource (name) VALUES ('Jane Doe');"
        "INSERT INTO hr_employee (name, resource_id, ssnid, sinid, "
        "spouse_complete_name, permit_no, visa_no, work_email, work_phone, "
        "mobile_phone) VALUES ('Jane Doe', 1, '123-45-6789', '046 454 286', "
        "'John Doe', 'P-778899', 'V-112233', 'jane@acme.com', "
        "'+1 555 0101', '+1 555 0102');",
    )
    result = CliRunner().invoke(sanitize, ["--db", name, "identity", "--force"])

    assert result.exit_code == 0, result.output
    employee_dump = pg_db.query(name, "SELECT row_to_json(e) FROM hr_employee e")
    resource_dump = pg_db.query(name, "SELECT row_to_json(r) FROM resource_resource r")
    dump = employee_dump + "\n" + resource_dump
    for leaked in (
        "Jane",
        "jane",
        "John",
        "6789",
        "454 286",
        "778899",
        "112233",
        "acme.com",
        "555 010",
    ):
        assert leaked not in dump, f"{leaked!r} survived sanitizing:\n{dump}"
    assert pg_db.query(name, "SELECT name FROM resource_resource") == pg_db.query(
        name, "SELECT name FROM hr_employee"
    )


def test_swapped_placeholder_logins_do_not_abort(in_project, pg_db):
    """Renaming logins to 'user<id>' must survive value swaps.

    When existing logins already look like placeholders in swapped
    positions (id 1 holds 'user2', id 2 holds 'user1'), a naive
    ``SET login = 'user' || id`` violates the unique constraint
    mid-statement and the whole sanitize aborts — the user is left with
    an untouched database and no explanation beyond a constraint error.
    """
    name = pg_db.create()
    pg_db.psql(
        name,
        "CREATE TABLE res_users ("
        "id int PRIMARY KEY, login varchar NOT NULL, "
        "CONSTRAINT res_users_login_key UNIQUE (login));"
        "INSERT INTO res_users (id, login) VALUES (1, 'user2'), (2, 'user1');"
        "CREATE TABLE res_partner (id serial PRIMARY KEY, name varchar);"
        "INSERT INTO res_partner (name) VALUES ('Jane Doe');",
    )
    result = CliRunner().invoke(sanitize, ["--db", name, "identity", "--force"])

    assert result.exit_code == 0, result.output
    logins = pg_db.query(name, "SELECT login FROM res_users ORDER BY id")
    assert logins.split() == ["user1", "user2"]


def test_identity_script_is_atomic(in_project, pg_db):
    """A failure inside 010_identity.sql rolls back the whole script.

    When the login rename fails — here a CHECK constraint rejects 'user%'
    logins — the partner masking that ran earlier in the same script must
    roll back too: a sanitized database must never be left
    half-anonymized.
    """
    name = pg_db.create()
    pg_db.psql(
        name,
        "CREATE TABLE res_users ("
        "id int PRIMARY KEY, login varchar NOT NULL, "
        "CONSTRAINT res_users_login_key UNIQUE (login), "
        "CHECK (login NOT LIKE 'user%'));"
        "INSERT INTO res_users (id, login) VALUES (1, 'alice'), (2, 'bob');"
        "CREATE TABLE res_partner (id serial PRIMARY KEY, name varchar);"
        "INSERT INTO res_partner (name) VALUES ('Jane Doe');",
    )
    result = CliRunner().invoke(sanitize, ["--db", name, "identity", "--force"])

    assert result.exit_code != 0
    assert pg_db.query(name, "SELECT name FROM res_partner") == "Jane Doe"


def test_zero_keep_days_from_project_config_is_honored(in_project, pg_db, monkeypatch):
    """``keep_days = 0`` in .osh/config.toml trims everything.

    TOML parses ``keep_days = 0`` as the integer 0, which the config
    reader treated as "unset" and silently fell back to the 30-day
    default — an explicit zero retention kept a month of rows.
    """
    monkeypatch.delenv("OSH_KEEP_DAYS", raising=False)
    name = pg_db.create()
    pg_db.psql(
        name,
        "CREATE TABLE mail_tracking_value ("
        "id serial PRIMARY KEY, create_date timestamp, "
        "old_value_char varchar);"
        "INSERT INTO mail_tracking_value (create_date, old_value_char) "
        "VALUES (now() - interval '1 hour', 'Jane Doe');",
    )
    (in_project / ".osh" / "config.toml").write_text("[trim]\nkeep_days = 0\n")

    result = CliRunner().invoke(sanitize, ["--db", name, "trim", "--force"])

    assert result.exit_code == 0, result.output
    assert pg_db.query(name, "SELECT count(*) FROM mail_tracking_value") == "0"


def test_trim_only_script_selection_with_both_groups(in_project, pg_db):
    """``--script`` picks scripts across both groups, not per group.

    ``osh db sanitize --script mail_message`` aborted with
    "Unknown script(s)" because each group validated the selection
    against only its own scripts — a trim script name is unknown to the
    anonymize set. The selection must resolve against the union, run the
    matching trim script, and leave anonymize untouched.
    """
    name = pg_db.create()
    result = CliRunner().invoke(
        sanitize, ["--db", name, "--script", "mail_message", "--force"]
    )

    assert result.exit_code == 0, result.output
    assert "Running trim script: 080_mail_message.sql" in result.output
    assert "Running anonymize script" not in result.output


def test_anonymize_only_skip_with_both_groups(in_project, pg_db):
    """``--skip`` drops scripts across groups without breaking the rest.

    ``osh db sanitize --skip address`` aborted because the trim group
    rejected 'address' as unknown — skip names must be validated against
    the union of both groups' scripts; anonymize loses
    050_address.sql while every trim script still runs.
    """
    name = pg_db.create()
    result = CliRunner().invoke(
        sanitize, ["--db", name, "--skip", "address", "--dry-run"]
    )

    assert result.exit_code == 0, result.output
    assert "Would run anonymize script: 010_identity.sql" in result.output
    assert "Would run trim script: 080_mail_message.sql" in result.output
    assert "050_address.sql" not in result.output


def test_selection_spanning_both_groups(in_project, pg_db):
    """``--script`` may mix anonymize and trim script names in one run.

    ``--script identity --script mail_message`` selects the identity
    anonymize script and the mail_message trim script together;
    unrelated scripts (050_address, 010_ir_logging) stay out.
    """
    name = pg_db.create()
    result = CliRunner().invoke(
        sanitize,
        [
            "--db",
            name,
            "--script",
            "identity",
            "--script",
            "mail_message",
            "--dry-run",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Would run anonymize script: 010_identity.sql" in result.output
    assert "Would run trim script: 080_mail_message.sql" in result.output
    assert "050_address.sql" not in result.output
    assert "010_ir_logging.sql" not in result.output


def test_unknown_script_is_rejected_before_any_sql_runs(in_project, pg_db):
    """An unknown ``--script`` name fails before any script executes.

    Guard for the union validation: a name matching nothing in either
    group is a usage error and no 'Running ...' line may appear.
    """
    name = pg_db.create()
    result = CliRunner().invoke(
        sanitize, ["--db", name, "--script", "bogus", "--force"]
    )

    assert result.exit_code != 0
    assert "Unknown script(s): bogus" in result.output
    assert "Running" not in result.output


def test_vacuum_returns_trimmed_space_to_disk(in_project, pg_db):
    """``--vacuum`` must rewrite trimmed tables so space goes back to disk.

    Plain VACUUM only marks dead space reusable — the relation file keeps
    its size, and with the recent rows physically last it cannot even
    truncate the tail. After trimming 20000 old rows, ``--vacuum`` must
    rewrite the table into a new file holding only the kept rows. The
    rewrite is asserted rather than the size: any open transaction on
    the server keeps deleted rows unremovable, even for VACUUM FULL.
    """
    name = pg_db.create()
    pg_db.psql(
        name,
        "CREATE TABLE mail_tracking_value ("
        "id serial PRIMARY KEY, create_date timestamp, pad text);"
        "ALTER TABLE mail_tracking_value "
        "SET (autovacuum_enabled = false);"
        "INSERT INTO mail_tracking_value (create_date, pad) "
        "SELECT now() - interval '400 days', repeat('x', 200) "
        "FROM generate_series(1, 20000);"
        "INSERT INTO mail_tracking_value (create_date, pad) "
        "SELECT now(), repeat('x', 200) FROM generate_series(1, 100);",
    )
    filenode = "SELECT pg_relation_filenode('mail_tracking_value')"
    before = pg_db.query(name, filenode)

    result = CliRunner().invoke(
        sanitize,
        ["--db", name, "trim", "--keep-days", "30", "--vacuum", "--force"],
    )

    assert result.exit_code == 0, result.output
    assert pg_db.query(name, "SELECT count(*) FROM mail_tracking_value") == "100"
    assert pg_db.query(name, filenode) != before, "vacuum did not rewrite the table"


def test_pre17_stored_display_name_keeps_company_prefix(in_project, pg_db):
    """On Odoo 10-16 the stored display_name keeps the company prefix.

    Pre-17 res_partner has no ``complete_name`` — the full
    "<company>, <contact>" name lives in the stored ``display_name``.
    Masking it to plain ``name`` loses the company prefix and breaks
    the coherence a user expects from the sanitized dump.
    """
    name = pg_db.create()
    pg_db.psql(
        name,
        "CREATE TABLE res_partner ("
        "id serial PRIMARY KEY, name varchar, display_name varchar, "
        "email varchar, is_company boolean, parent_id int, "
        "commercial_partner_id int, company_name varchar, "
        "commercial_company_name varchar);"
        "INSERT INTO res_partner (id, name, display_name, is_company, "
        "parent_id, commercial_partner_id, commercial_company_name) "
        "VALUES (1, 'Acme Corp', 'Acme Corp', true, NULL, 1, 'Acme Corp'), "
        "(2, 'Jane Doe', 'Acme Corp, Jane Doe', false, 1, 1, 'Acme Corp');",
    )
    result = CliRunner().invoke(sanitize, ["--db", name, "identity", "--force"])

    assert result.exit_code == 0, result.output
    dump = pg_db.query(name, "SELECT row_to_json(p) FROM res_partner p ORDER BY id")
    for leaked in ("Jane", "Acme"):
        assert leaked not in dump, f"{leaked!r} survived sanitizing:\n{dump}"
    rows = [json.loads(line) for line in dump.splitlines()]
    by_id = {row["id"]: row for row in rows}
    assert by_id[1]["display_name"] == "Partner 1"
    assert by_id[2]["display_name"] == "Partner 1, Partner 2"


def test_odoo10_employee_names_live_on_the_resource(in_project, pg_db):
    """On Odoo 10 the employee name lives on resource_resource.

    Odoo 10's hr_employee inherits resource.resource — there is no
    ``name`` column, only the stored ``name_related`` copy — so masking
    must rewrite ``resource_resource.name`` and ``name_related``
    instead of relying on ``hr_employee.name``.
    """
    name = pg_db.create()
    pg_db.psql(
        name,
        "CREATE TABLE resource_resource (id serial PRIMARY KEY, name varchar);"
        "CREATE TABLE hr_employee ("
        "id serial PRIMARY KEY, resource_id int, name_related varchar, "
        "ssnid varchar, work_email varchar);"
        "INSERT INTO resource_resource (name) VALUES ('Jane Doe');"
        "INSERT INTO hr_employee (resource_id, name_related, ssnid, "
        "work_email) VALUES (1, 'Jane Doe', '123-45-6789', 'jane@acme.com');",
    )
    result = CliRunner().invoke(sanitize, ["--db", name, "identity", "--force"])

    assert result.exit_code == 0, result.output
    employee_dump = pg_db.query(name, "SELECT row_to_json(e) FROM hr_employee e")
    resource_dump = pg_db.query(name, "SELECT row_to_json(r) FROM resource_resource r")
    dump = employee_dump + "\n" + resource_dump
    for leaked in ("Jane", "jane", "6789"):
        assert leaked not in dump, f"{leaked!r} survived sanitizing:\n{dump}"
    assert (
        pg_db.query(name, "SELECT name FROM resource_resource")
        == pg_db.query(name, "SELECT name_related FROM hr_employee")
        == "Employee 1"
    )


def test_partner_without_company_columns_still_masks_full_name(in_project, pg_db):
    """A minimal res_partner still gets a coherent display_name.

    Databases whose res_partner lacks the company columns entirely only
    need ``display_name`` set to the placeholder ``name`` — the
    full-name CASE must not run (or fail) when its inputs are absent.
    """
    name = pg_db.create()
    pg_db.psql(
        name,
        "CREATE TABLE res_partner ("
        "id serial PRIMARY KEY, name varchar, display_name varchar);"
        "INSERT INTO res_partner (name, display_name) VALUES "
        "('Jane Doe', 'Jane Doe');",
    )
    result = CliRunner().invoke(sanitize, ["--db", name, "identity", "--force"])

    assert result.exit_code == 0, result.output
    assert pg_db.query(name, "SELECT display_name FROM res_partner") == "Partner 1"
