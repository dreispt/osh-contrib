"""Tests for the ``osh update`` command."""

import json

from click.testing import CliRunner

from osh_update import store
from osh_update.commands import update
from osh_update.fingerprint import fingerprint_module


def _stored_fingerprints(pg_db, db_name):
    """Return the stored fingerprint map from the test database."""
    value = pg_db.query(
        db_name,
        "SELECT value FROM ir_config_parameter "
        f"WHERE key = '{store.FINGERPRINT_PARAM}'",
    )
    return json.loads(value) if value else None


def _store_fingerprints(pg_db, db_name, mapping):
    """Write *mapping* as the fingerprint param in the test database."""
    pg_db.psql(
        db_name,
        "INSERT INTO ir_config_parameter (key, value) VALUES "
        f"('{store.FINGERPRINT_PARAM}', $${json.dumps(mapping)}$$)",
    )


# Fingerprinting ---------------------------------------------------------


def test_fingerprint_changes_on_code_change(module_dir):
    module = module_dir("my_mod", files={"models.py": "a = 1\n"})
    before = fingerprint_module(module)
    (module / "models.py").write_text("a = 2\n")
    assert fingerprint_module(module) != before


def test_fingerprint_changes_on_data_change(module_dir):
    module = module_dir("my_mod")
    before = fingerprint_module(module)
    (module / "data").mkdir()
    (module / "data" / "records.xml").write_text("<odoo/>\n")
    assert fingerprint_module(module) != before


def test_fingerprint_ignores_static(module_dir):
    module = module_dir("my_mod")
    before = fingerprint_module(module)
    static = module / "static" / "src"
    static.mkdir(parents=True)
    (static / "app.js").write_text("console.log(1)\n")
    (static / "app.css").write_text("body {}\n")
    assert fingerprint_module(module) == before


def test_fingerprint_ignores_pycache(module_dir):
    module = module_dir("my_mod")
    before = fingerprint_module(module)
    cache = module / "__pycache__"
    cache.mkdir()
    (cache / "models.cpython-314.pyc").write_bytes(b"\x00\x01")
    assert fingerprint_module(module) == before


def test_fingerprint_nested_repos(tmp_project, module_dir):
    """Nested repos are included by default, skipped with skip_nested."""
    from osh_update.fingerprint import fingerprint_project_modules

    module_dir("my_mod")
    for repo in ("odoo", "enterprise"):
        source = tmp_project / repo
        source.mkdir()
        (source / ".git").touch()  # submodule/clone marker
        (source / f"{repo}_mod").mkdir()
        (source / f"{repo}_mod" / "__manifest__.py").write_text("{}\n")

    discovered = fingerprint_project_modules(tmp_project)
    assert set(discovered) == {"my_mod", "odoo_mod", "enterprise_mod"}

    filtered = fingerprint_project_modules(tmp_project, skip_nested=True)
    assert filtered == {"my_mod": fingerprint_module(tmp_project / "my_mod")}


# Command behaviour ------------------------------------------------------


def test_update_baselines_on_first_run(in_project, module_dir, pg_db, capture_update):
    """First run fingerprints installed modules only, with no update."""
    db_name = pg_db.make_odoo_db(modules=[("my_mod", "installed")])
    module = module_dir("my_mod")
    module_dir("not_installed")

    result = CliRunner().invoke(update, ["--db", db_name])

    assert result.exit_code == 0
    assert "baseline" in result.output.lower()
    assert capture_update == []
    stored = _stored_fingerprints(pg_db, db_name)
    assert stored == {"my_mod": fingerprint_module(module)}


def test_update_detects_changed_module(in_project, module_dir, pg_db, capture_update):
    """A module whose stored fingerprint differs is updated."""
    db_name = pg_db.make_odoo_db(modules=[("my_mod", "installed")])
    module = module_dir("my_mod")
    module_dir("not_installed")
    _store_fingerprints(pg_db, db_name, {"my_mod": "deadbeef"})

    result = CliRunner().invoke(update, ["--db", db_name])

    assert result.exit_code == 0
    assert capture_update == [
        (
            ["my_mod"],
            db_name,
            {"backend_name": None, "compose_file": None, "dry_run": False},
        )
    ]
    stored = _stored_fingerprints(pg_db, db_name)
    assert stored == {"my_mod": fingerprint_module(module)}


def test_update_reports_up_to_date(in_project, module_dir, pg_db, capture_update):
    """Matching fingerprints produce no update run."""
    db_name = pg_db.make_odoo_db(modules=[("my_mod", "installed")])
    module = module_dir("my_mod")
    _store_fingerprints(pg_db, db_name, {"my_mod": fingerprint_module(module)})

    result = CliRunner().invoke(update, ["--db", db_name])

    assert result.exit_code == 0
    assert "up to date" in result.output.lower()
    assert capture_update == []


def test_update_skips_not_installed_modules(
    in_project, module_dir, pg_db, capture_update
):
    """Modules that are uninstalled, pending install or pending removal
    are silently skipped — ``-u`` on a ``to remove`` module would cancel
    the pending uninstall."""
    db_name = pg_db.make_odoo_db(
        modules=[
            ("uninstalled_mod", "uninstalled"),
            ("queued_mod", "to install"),
            ("doomed_mod", "to remove"),
        ]
    )
    module_dir("uninstalled_mod")
    module_dir("queued_mod")
    module_dir("doomed_mod")
    _store_fingerprints(pg_db, db_name, {})

    result = CliRunner().invoke(update, ["--db", db_name])

    assert result.exit_code == 0
    assert capture_update == []


def test_update_dry_run_lists_modules(in_project, module_dir, pg_db, capture_update):
    """--dry-run lists the modules that would be updated."""
    db_name = pg_db.make_odoo_db(modules=[("my_mod", "installed")])
    module_dir("my_mod")
    _store_fingerprints(pg_db, db_name, {"my_mod": "deadbeef"})

    result = CliRunner().invoke(update, ["--db", db_name, "--dry-run"])

    assert result.exit_code == 0
    assert "Would update (1):\nmy_mod" in result.output


def test_update_recovers_corrupt_fingerprint_param(
    in_project, module_dir, pg_db, capture_update
):
    """A non-JSON fingerprint param warns and records a fresh baseline."""
    db_name = pg_db.make_odoo_db(modules=[("my_mod", "installed")])
    module = module_dir("my_mod")
    pg_db.psql(
        db_name,
        "INSERT INTO ir_config_parameter (key, value) VALUES "
        f"('{store.FINGERPRINT_PARAM}', 'not-json')",
    )

    result = CliRunner().invoke(update, ["--db", db_name])

    assert result.exit_code == 0
    assert "not a JSON object" in result.output
    assert "baseline" in result.output.lower()
    assert capture_update == []
    assert _stored_fingerprints(pg_db, db_name) == {
        "my_mod": fingerprint_module(module)
    }


def test_update_fails_on_uninitialized_db(in_project, pg_db, capture_update):
    """A database without ir_module_module produces a helpful error."""
    db_name = pg_db.create()

    result = CliRunner().invoke(update, ["--db", db_name])

    assert result.exit_code != 0
    assert "not initialized" in result.output
    assert capture_update == []


def test_update_dry_run_does_not_write(in_project, module_dir, pg_db, capture_update):
    """--dry-run reports the update but stores no fingerprints."""
    db_name = pg_db.make_odoo_db(modules=[("my_mod", "installed")])
    module_dir("my_mod")
    _store_fingerprints(pg_db, db_name, {"my_mod": "deadbeef"})

    result = CliRunner().invoke(update, ["--db", db_name, "--dry-run"])

    assert result.exit_code == 0
    assert capture_update == [
        (
            ["my_mod"],
            db_name,
            {"backend_name": None, "compose_file": None, "dry_run": True},
        )
    ]
    assert _stored_fingerprints(pg_db, db_name) == {"my_mod": "deadbeef"}


def test_update_no_submodules_flag(
    in_project, tmp_project, module_dir, pg_db, capture_update
):
    """--no-submodules excludes modules inside nested git repos."""
    db_name = pg_db.make_odoo_db(
        modules=[("my_mod", "installed"), ("odoo_mod", "installed")]
    )
    module_dir("my_mod")
    source = tmp_project / "odoo"
    source.mkdir()
    (source / ".git").touch()
    (source / "odoo_mod").mkdir()
    (source / "odoo_mod" / "__manifest__.py").write_text("{}\n")
    _store_fingerprints(pg_db, db_name, {})

    result = CliRunner().invoke(update, ["--db", db_name, "--no-submodules"])

    assert result.exit_code == 0
    assert capture_update[0][0] == ["my_mod"]


def test_update_positional_modules_force_update(
    in_project, module_dir, pg_db, capture_update
):
    """Named modules are updated regardless of fingerprints."""
    db_name = pg_db.make_odoo_db(modules=[("my_mod", "installed")])
    module = module_dir("my_mod")

    result = CliRunner().invoke(update, ["--db", db_name, "my_mod", "other_mod"])

    assert result.exit_code == 0
    assert capture_update == [
        (
            ["my_mod", "other_mod"],
            db_name,
            {"backend_name": None, "compose_file": None, "dry_run": False},
        )
    ]
    stored = _stored_fingerprints(pg_db, db_name)
    assert stored == {"my_mod": fingerprint_module(module)}


def test_update_all_forces_installed_third_party_modules(
    in_project, tmp_project, module_dir, pg_db, capture_update
):
    """--all updates installed modules outside the upstream source trees."""
    db_name = pg_db.make_odoo_db(
        modules=[
            ("my_mod", "installed"),
            ("skipped_mod", "uninstalled"),
            ("base", "installed"),
        ]
    )
    module_dir("my_mod")
    module_dir("skipped_mod")
    odoo_dir = tmp_project / "odoo"
    odoo_dir.mkdir()
    (odoo_dir / ".git").touch()
    (odoo_dir / "base").mkdir()
    (odoo_dir / "base" / "__manifest__.py").write_text("{}\n")

    result = CliRunner().invoke(update, ["--db", db_name, "--all"])

    assert result.exit_code == 0
    assert capture_update[0][0] == ["my_mod"]


def _make_upstream_module(tmp_project, name="base"):
    """Create a module inside an ``odoo`` source checkout."""
    odoo_dir = tmp_project / "odoo"
    odoo_dir.mkdir(exist_ok=True)
    (odoo_dir / ".git").touch()
    (odoo_dir / name).mkdir(exist_ok=True)
    (odoo_dir / name / "__manifest__.py").write_text("{}\n")
    return odoo_dir / name


def test_update_status_reports_installed_and_changed(
    in_project, tmp_project, module_dir, pg_db, capture_update
):
    """--status lists installed third-party modules and pending updates."""
    db_name = pg_db.make_odoo_db(
        modules=[
            ("my_mod", "installed"),
            ("synced_mod", "installed"),
            ("skipped_mod", "uninstalled"),
            ("base", "installed"),
        ]
    )
    module_dir("my_mod")
    synced = module_dir("synced_mod")
    module_dir("skipped_mod")
    _make_upstream_module(tmp_project)
    _store_fingerprints(
        pg_db,
        db_name,
        {
            "my_mod": "deadbeef",
            "synced_mod": fingerprint_module(synced),
            "base": "deadbeef",
        },
    )

    result = CliRunner().invoke(update, ["--db", db_name, "--status"])

    assert result.exit_code == 0
    assert "Installed modules (2):\nmy_mod,synced_mod" in result.output
    assert "skipped_mod" not in result.output
    assert "base" not in result.output
    assert "Modules to update (1):\nmy_mod" in result.output
    assert capture_update == []
    assert _stored_fingerprints(pg_db, db_name)["my_mod"] == "deadbeef"


def test_update_status_per_line(in_project, module_dir, pg_db, capture_update):
    """-1/--per-line prints module lists one module per line."""
    db_name = pg_db.make_odoo_db(
        modules=[("my_mod", "installed"), ("synced_mod", "installed")]
    )
    module_dir("my_mod")
    module_dir("synced_mod")
    _store_fingerprints(pg_db, db_name, {})

    result = CliRunner().invoke(update, ["--db", db_name, "--status", "-1"])

    assert result.exit_code == 0
    assert "Installed modules (2):\n  my_mod\n  synced_mod" in result.output


def test_update_status_all_includes_upstream(
    in_project, tmp_project, module_dir, pg_db, capture_update
):
    """--status --all widens the report to upstream modules."""
    db_name = pg_db.make_odoo_db(
        modules=[("my_mod", "installed"), ("base", "installed")]
    )
    module_dir("my_mod")
    upstream = _make_upstream_module(tmp_project)
    _store_fingerprints(
        pg_db,
        db_name,
        {"my_mod": "deadbeef", "base": fingerprint_module(upstream)},
    )

    result = CliRunner().invoke(update, ["--db", db_name, "--status", "--all"])

    assert result.exit_code == 0
    assert "Installed modules (2):\nbase,my_mod" in result.output
    assert "Modules to update (1):\nmy_mod" in result.output
    assert capture_update == []


def test_update_status_first_run_baselines(
    in_project, tmp_project, module_dir, pg_db, capture_update
):
    """--status with no stored fingerprints records the baseline.

    The report lists third-party modules only, but the baseline still
    covers all installed modules — otherwise a later plain ``osh update``
    would flag every upstream module as changed.
    """
    db_name = pg_db.make_odoo_db(
        modules=[("my_mod", "installed"), ("base", "installed")]
    )
    module = module_dir("my_mod")
    upstream = _make_upstream_module(tmp_project)

    result = CliRunner().invoke(update, ["--db", db_name, "--status"])

    assert result.exit_code == 0
    assert "Installed modules (1):\nmy_mod\n" in result.output
    assert "baseline" in result.output.lower()
    assert capture_update == []
    assert _stored_fingerprints(pg_db, db_name) == {
        "my_mod": fingerprint_module(module),
        "base": fingerprint_module(upstream),
    }


def test_update_status_up_to_date(in_project, module_dir, pg_db, capture_update):
    """--status reports no pending updates when fingerprints match."""
    db_name = pg_db.make_odoo_db(modules=[("my_mod", "installed")])
    module = module_dir("my_mod")
    _store_fingerprints(pg_db, db_name, {"my_mod": fingerprint_module(module)})

    result = CliRunner().invoke(update, ["--db", db_name, "--status"])

    assert result.exit_code == 0
    assert "Modules to update: none" in result.output


def test_update_status_rejects_modules(in_project):
    result = CliRunner().invoke(update, ["my_mod", "--status"])
    assert result.exit_code != 0


def test_update_rejects_modules_and_all(in_project):
    result = CliRunner().invoke(update, ["my_mod", "--all"])
    assert result.exit_code != 0
    assert "not both" in result.output


def test_update_outside_project(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(update, [])
    assert result.exit_code == 0
    assert "Not inside an Osh project" in result.output
