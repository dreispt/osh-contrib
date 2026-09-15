"""Tests for the ``osh addon uninstall`` command."""

from click.testing import CliRunner

from osh_uninstall import core
from osh_uninstall.commands import uninstall


def _add_dependency(pg_db, db_name, module, depends_on):
    """Record that *module* depends on *depends_on*."""
    pg_db.psql(
        db_name,
        "INSERT INTO ir_module_module_dependency (module_id, name) "
        "VALUES ((SELECT id FROM ir_module_module "
        f"WHERE name='{module}'), '{depends_on}')",
    )


def test_uninstall_removes_module(in_project, pg_db, capture_uninstall):
    """An installed module is uninstalled after confirmation."""
    db_name = pg_db.make_odoo_db(modules=[("my_mod", "installed")])

    result = CliRunner().invoke(uninstall, ["my_mod", "--db", db_name], input="y\n")

    assert result.exit_code == 0
    assert capture_uninstall == [(["my_mod"], db_name, {})]
    assert "Uninstalled 1 module(s)" in result.output


def test_uninstall_parses_comma_list(in_project, pg_db, capture_uninstall):
    """A comma-separated list is split, stripped, deduplicated, sorted."""
    db_name = pg_db.make_odoo_db(
        modules=[("mod_a", "installed"), ("mod_b", "installed")]
    )

    result = CliRunner().invoke(
        uninstall, [" mod_b ,,mod_a,mod_a ", "--db", db_name, "--yes"]
    )

    assert result.exit_code == 0
    assert capture_uninstall[0][0] == ["mod_a", "mod_b"]


def test_uninstall_lists_dependents(in_project, pg_db, capture_uninstall):
    """Installed dependents are previewed and counted in the summary."""
    db_name = pg_db.make_odoo_db(
        modules=[
            ("base_mod", "installed"),
            ("child_mod", "installed"),
            ("grandchild", "installed"),
        ]
    )
    _add_dependency(pg_db, db_name, "child_mod", "base_mod")
    _add_dependency(pg_db, db_name, "grandchild", "child_mod")

    result = CliRunner().invoke(uninstall, ["base_mod", "--db", db_name, "--yes"])

    assert result.exit_code == 0
    assert "Dependents will also be uninstalled: child_mod, grandchild" in result.output
    assert "Uninstalled 3 module(s)" in result.output


def test_uninstall_skips_dead_dependents(in_project, pg_db, capture_uninstall):
    """Dependents in dead states are neither listed nor counted."""
    db_name = pg_db.make_odoo_db(
        modules=[
            ("base_mod", "installed"),
            ("gone_mod", "uninstalled"),
            ("doomed_mod", "to remove"),
        ]
    )
    _add_dependency(pg_db, db_name, "gone_mod", "base_mod")
    _add_dependency(pg_db, db_name, "doomed_mod", "base_mod")

    result = CliRunner().invoke(uninstall, ["base_mod", "--db", db_name, "--yes"])

    assert result.exit_code == 0
    assert "gone_mod" not in result.output
    assert "doomed_mod" not in result.output
    assert "Uninstalled 1 module(s)" in result.output


def test_uninstall_rejects_not_installed(in_project, pg_db, capture_uninstall):
    """Modules not installed are rejected before anything runs."""
    db_name = pg_db.make_odoo_db(
        modules=[
            ("gone", "uninstalled"),
            ("queued", "to install"),
            ("doomed", "to remove"),
        ]
    )

    result = CliRunner().invoke(
        uninstall, ["gone,queued,doomed,missing", "--db", db_name]
    )

    assert result.exit_code != 0
    assert "gone (uninstalled)" in result.output
    assert "queued (to install)" in result.output
    assert "doomed (to remove)" in result.output
    assert "missing (unknown)" in result.output
    assert capture_uninstall == []


def test_uninstall_fails_on_uninitialized_db(in_project, pg_db, capture_uninstall):
    """A database without ir_module_module produces a helpful error."""
    db_name = pg_db.create()

    result = CliRunner().invoke(uninstall, ["my_mod", "--db", db_name])

    assert result.exit_code != 0
    assert "not initialized" in result.output
    assert capture_uninstall == []


def test_uninstall_aborts_on_decline(in_project, pg_db, capture_uninstall):
    """Answering no to the confirmation aborts without running."""
    db_name = pg_db.make_odoo_db(modules=[("my_mod", "installed")])

    result = CliRunner().invoke(uninstall, ["my_mod", "--db", db_name], input="n\n")

    assert result.exit_code == 0
    assert capture_uninstall == []


def test_uninstall_dry_run(in_project, pg_db, capture_uninstall):
    """--dry-run shows the script and would-run command, changing nothing."""
    db_name = pg_db.make_odoo_db(modules=[("my_mod", "installed")])

    result = CliRunner().invoke(uninstall, ["my_mod", "--db", db_name, "--dry-run"])

    assert result.exit_code == 0
    assert "button_immediate_uninstall" in result.output
    assert capture_uninstall == [(["my_mod"], db_name, {"dry_run": True})]
    state = pg_db.query(
        db_name,
        "SELECT state FROM ir_module_module WHERE name='my_mod'",
    )
    assert state == "installed"


def test_uninstall_reports_failure(in_project, pg_db, monkeypatch):
    """A non-zero shell exit becomes a clear error."""
    db_name = pg_db.make_odoo_db(modules=[("my_mod", "installed")])
    monkeypatch.setattr(core, "run_uninstall", lambda *a, **k: 1)

    result = CliRunner().invoke(uninstall, ["my_mod", "--db", db_name, "--yes"])

    assert result.exit_code != 0
    assert "uninstall failed (exit 1)" in result.output


def test_uninstall_detects_silent_failure(in_project, pg_db, monkeypatch):
    """A zero exit without a state change is still reported as failure."""
    db_name = pg_db.make_odoo_db(modules=[("my_mod", "installed")])
    monkeypatch.setattr(core, "run_uninstall", lambda *a, **k: 0)

    result = CliRunner().invoke(uninstall, ["my_mod", "--db", db_name, "--yes"])

    assert result.exit_code != 0
    assert "were not uninstalled" in result.output


def test_uninstall_requires_modules(in_project):
    result = CliRunner().invoke(uninstall, [])
    assert result.exit_code != 0


def test_uninstall_rejects_blank_list(in_project):
    result = CliRunner().invoke(uninstall, [" , "])
    assert result.exit_code != 0
    assert "No module names given" in result.output


def test_uninstall_outside_project(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(uninstall, ["my_mod"])
    assert result.exit_code == 0
    assert "Not inside an Osh project" in result.output
