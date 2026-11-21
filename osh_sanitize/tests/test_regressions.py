"""Regression tests for ``osh db sanitize`` issues found in review.

Each test encodes a user-facing bug as a story: sanitizing must mask
stored identity fields coherently, preserve user credentials,
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
    """A developer can match masked contacts and companies to production.

    Derived display fields retain the masked company prefix, while contact
    details and the full original names do not survive the sanitize run.
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
    company, contact = rows
    assert company["name"] == "A*** C***"
    assert contact["name"] == "J*** D***"
    assert contact["commercial_company_name"] == company["name"]
    assert contact["complete_name"] == contact["display_name"] == "A*** C***, J*** D***"
    assert (
        contact["email"]
        == contact["email_normalized"]
        == "j-masked-partner-2@example.invalid"
    )
    assert contact["phone"] == contact["phone_sanitized"] == "xxxx0100"


def test_neutralized_placeholder_email_does_not_supply_a_production_initial(
    in_project, pg_db
):
    """Core's dev+<id>@example.local fallback has no usable initial.

    Sanitizing a database already neutralized by core must not treat the
    fallback address as a production email — the masked address carries
    no letter prefix.
    """
    name = pg_db.create()
    pg_db.psql(
        name,
        "CREATE TABLE res_partner ("
        "id int PRIMARY KEY, email varchar, email_normalized varchar);"
        "INSERT INTO res_partner (id, email, email_normalized) VALUES "
        "(7, 'dev+7@example.local', 'jane@example.com'), "
        "(8, 'dev+8@example.com', 'dev+8@example.com');",
    )
    for _ in range(2):
        result = CliRunner().invoke(sanitize, ["--db", name, "identity", "--force"])
        assert result.exit_code == 0, result.output
    rows = pg_db.query(
        name,
        "SELECT email || '|' || email_normalized FROM res_partner ORDER BY id",
    )
    assert rows.splitlines() == [
        "masked-partner-7@example.invalid|masked-partner-7@example.invalid",
        "d-masked-partner-8@example.invalid|d-masked-partner-8@example.invalid",
    ]


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
        "id serial PRIMARY KEY, partner_id int, acc_number varchar, "
        "sanitized_acc_number varchar, acc_holder_name varchar, "
        "allow_out_payment boolean, clearing_number varchar, "
        "UNIQUE (sanitized_acc_number, partner_id));"
        "INSERT INTO res_partner_bank "
        "(partner_id, acc_number, sanitized_acc_number, acc_holder_name, "
        "allow_out_payment, clearing_number) VALUES "
        "(7, 'BE68 5390 0754 7034', 'BE68539007547034', 'Jane Doe', "
        "true, '12345678'), "
        "(7, 'BE99 9000 1111 7034', 'BE99900011117034', 'Jane Doe', "
        "true, '12345678');",
    )
    result = CliRunner().invoke(sanitize, ["--db", name, "identity", "--force"])

    assert result.exit_code == 0, result.output
    dump = pg_db.query(
        name, "SELECT row_to_json(b) FROM res_partner_bank b ORDER BY id"
    )
    for leaked in ("539007547034", "5390 0754", "Jane", "BE68"):
        assert leaked not in dump, f"{leaked!r} survived sanitizing:\n{dump}"
    first, second = (json.loads(line) for line in dump.splitlines())
    assert first["acc_number"] == first["sanitized_acc_number"] == "MASKED1X7034"
    assert second["acc_number"] == second["sanitized_acc_number"] == "MASKED2X7034"
    for row in (first, second):
        assert row["acc_holder_name"] == "J*** D***"
        assert row["clearing_number"] == "xxxx5678"
        assert row["partner_id"] == 7
        assert row["allow_out_payment"] is False


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
    masked = pg_db.query(
        name,
        "SELECT work_email || '|' || work_phone || '|' || mobile_phone "
        "FROM hr_employee",
    )
    assert masked == "j-masked-employee-1@example.invalid|xxxx0101|xxxx0102"


def test_only_internal_user_logins_and_names_are_preserved(in_project, pg_db):
    """Only internal users keep their logins and account names.

    Developers keep their credentials on a sanitized database:
    ``res_users`` rows with ``share = false`` keep their login, and a
    partner referenced by an internal user's ``partner_id`` keeps its
    name — it is the user's display name. Portal users
    (``share = true``) get their login masked like an email and their
    partner's name partially masked like every other partner.
    """
    name = pg_db.create()
    pg_db.psql(
        name,
        "CREATE TABLE res_users ("
        "id int PRIMARY KEY, login varchar NOT NULL, partner_id int, "
        "share boolean, "
        "CONSTRAINT res_users_login_key UNIQUE (login));"
        "INSERT INTO res_users (id, login, partner_id, share) VALUES "
        "(1, 'alice', 1, false), (2, 'bob', 2, false), "
        "(3, 'jane.doe@example.com', 3, true);"
        "CREATE TABLE res_partner (id serial PRIMARY KEY, name varchar);"
        "INSERT INTO res_partner (id, name) VALUES "
        "(1, 'Alice Dev'), (2, 'Bob Dev'), (3, 'Jane Doe');",
    )
    result = CliRunner().invoke(sanitize, ["--db", name, "identity", "--force"])

    assert result.exit_code == 0, result.output
    logins = pg_db.query(
        name, "SELECT string_agg(login, '|' ORDER BY id) FROM res_users"
    )
    assert logins == "alice|bob|j-masked-user-3@example.invalid"
    partners = pg_db.query(
        name, "SELECT string_agg(name, '|' ORDER BY id) FROM res_partner"
    )
    assert partners == "Alice Dev|Bob Dev|J*** D***"


def test_identity_script_is_atomic(in_project, pg_db):
    """A failure inside 010_identity.sql rolls back the whole script.

    When the email masking fails — here a CHECK constraint rejects the
    '@example.invalid' placeholder — the partner name masking that already
    ran must roll back too: a sanitized database must never be left
    half-anonymized.
    """
    name = pg_db.create()
    pg_db.psql(
        name,
        "CREATE TABLE res_partner ("
        "id serial PRIMARY KEY, name varchar, "
        "email varchar, "
        "CONSTRAINT res_partner_email_check "
        "CHECK (email NOT LIKE '%@example.invalid'));"
        "INSERT INTO res_partner (id, name, email) VALUES "
        "(1, 'Jane Doe', 'jane@example.com');",
    )
    result = CliRunner().invoke(sanitize, ["--db", name, "identity", "--force"])

    assert result.exit_code != 0
    assert "res_partner_email_check" in result.output
    assert pg_db.query(name, "SELECT name FROM res_partner") == "Jane Doe"
    assert pg_db.query(name, "SELECT email FROM res_partner") == "jane@example.com"


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
    assert by_id[1]["display_name"] == "A*** C***"
    assert by_id[2]["display_name"] == "A*** C***, J*** D***"


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
    need ``display_name`` set to the masked ``name`` — the
    full-name CASE must not run (or fail) when its inputs are absent.
    """
    name = pg_db.create()
    pg_db.psql(
        name,
        "CREATE TABLE res_partner ("
        "id serial PRIMARY KEY, name varchar, display_name varchar);"
        "INSERT INTO res_partner (name, display_name) VALUES "
        "('Jane Doe', 'Jane Doe'), ('Al O''Neil', 'Al O''Neil'), "
        "('', ''), (NULL, NULL);",
    )
    for _ in range(2):
        result = CliRunner().invoke(sanitize, ["--db", name, "--no-trim", "--force"])

        assert result.exit_code == 0, result.output
        rows = pg_db.query(name, "SELECT row_to_json(p) FROM res_partner p ORDER BY id")
        assert [json.loads(line)["display_name"] for line in rows.splitlines()] == [
            "J*** D***",
            "*** ***'N***",
            "",
            None,
        ]


def test_partial_address_retains_geography(in_project, pg_db):
    """Masked addresses keep geography but drop identifying detail.

    As a developer matching sanitized records to production, I expect
    city, state and country to survive so records stay placeable, while
    street lines keep only initials and postcodes keep at most their
    leading pair — on partner fields and private employee fields alike,
    across the column sets different Odoo versions actually have.
    """
    name = pg_db.create()
    pg_db.psql(
        name,
        "CREATE TABLE res_partner ("
        "id serial PRIMARY KEY, street varchar, city varchar, "
        "zip varchar, country_id int);"
        "INSERT INTO res_partner (street, city, zip, country_id) VALUES "
        "('12 Main Street', 'Porto', '4050-123', 1), "
        "('7 Oak Road', 'Braga', 'X2', 1);"
        "CREATE TABLE hr_employee ("
        "id serial PRIMARY KEY, private_street2 varchar, "
        "private_city varchar, private_zip varchar);"
        "INSERT INTO hr_employee (private_street2, private_city, "
        "private_zip) VALUES ('Suite 42', 'Porto', '4100-111');",
    )
    for _ in range(2):
        result = CliRunner().invoke(sanitize, ["--db", name, "address", "--force"])

        assert result.exit_code == 0, result.output
        partners = [
            json.loads(line)
            for line in pg_db.query(
                name, "SELECT row_to_json(p) FROM res_partner p ORDER BY id"
            ).splitlines()
        ]
        assert [
            (row["street"], row["city"], row["zip"], row["country_id"])
            for row in partners
        ] == [
            ("*** M*** S***", "Porto", "40***", 1),
            ("*** O*** R***", "Braga", "***", 1),
        ]
        employees = [
            json.loads(line)
            for line in pg_db.query(
                name, "SELECT row_to_json(e) FROM hr_employee e ORDER BY id"
            ).splitlines()
        ]
        assert [
            (row["private_street2"], row["private_city"], row["private_zip"])
            for row in employees
        ] == [("S*** ***", "Porto", "41***")]


def test_partial_payment_details_keep_no_provider_credentials(in_project, pg_db):
    """Masked payment tokens keep only hints and synthetic token IDs.

    As a developer auditing a sanitized copy, I expect token rows to keep
    their IDs and partner links while every provider credential, customer
    reference and contact email is replaced by a per-record synthetic
    value — a trailing-four-digits hint is enough to recognize the
    instrument without retaining live provider references.
    """
    name = pg_db.create()
    pg_db.psql(
        name,
        "CREATE TABLE payment_token ("
        "id serial PRIMARY KEY, partner_id int, active boolean, "
        "payment_details varchar, name varchar, provider_ref varchar, "
        "acquirer_ref varchar, stripe_payment_method varchar, "
        "stripe_mandate varchar, adyen_shopper_reference varchar, "
        "authorize_profile varchar, mercado_pago_customer_id varchar, "
        "mollie_customer_id varchar, flutterwave_customer_email varchar);"
        "INSERT INTO payment_token (id, partner_id, active, "
        "payment_details, name, provider_ref, acquirer_ref, "
        "stripe_payment_method, stripe_mandate, adyen_shopper_reference, "
        "authorize_profile, mercado_pago_customer_id, mollie_customer_id, "
        "flutterwave_customer_email) VALUES "
        "(1, 7, true, 'Visa 4242', 'Card 1234', 'secret-provider', "
        "'secret-acquirer', 'secret-stripe', 'secret-mandate', "
        "'secret-shopper', 'secret-profile', 'secret-customer', "
        "'secret-mollie', 'alice@example.com'),"
        "(2, 7, NULL, 'no digits', NULL, 'other-secret', "
        "NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL);",
    )
    for _ in range(2):
        result = CliRunner().invoke(sanitize, ["--db", name, "identity", "--force"])

        assert result.exit_code == 0, result.output
        dump = pg_db.query(
            name, "SELECT row_to_json(t) FROM payment_token t ORDER BY id"
        )
        for leaked in (
            "secret-provider",
            "secret-acquirer",
            "secret-stripe",
            "secret-mandate",
            "secret-shopper",
            "secret-profile",
            "secret-customer",
            "secret-mollie",
            "other-secret",
            "alice@example.com",
            "Visa",
            "Card 1234",
            "no digits",
        ):
            assert leaked not in dump, f"{leaked!r} survived sanitizing:\n{dump}"
        first, second = (json.loads(line) for line in dump.splitlines())
        assert first["payment_details"] == "****4242"
        assert first["name"] == "****1234"
        assert first["flutterwave_customer_email"] == "a-masked-token-1@example.invalid"
        for field in (
            "provider_ref",
            "acquirer_ref",
            "stripe_payment_method",
            "stripe_mandate",
            "adyen_shopper_reference",
            "authorize_profile",
            "mercado_pago_customer_id",
            "mollie_customer_id",
        ):
            assert first[field] == "osh-disabled-token-1", field
        assert first["partner_id"] == 7
        assert first["active"] is False
        assert second["payment_details"] == "****"
        assert second["provider_ref"] == "osh-disabled-token-2"
        assert second["name"] is None
        assert second["mollie_customer_id"] is None
        assert second["partner_id"] == 7
        assert second["active"] is False
