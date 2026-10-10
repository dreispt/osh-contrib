"""Tests for the ``osh apps update``/``osh apps install``/``osh apps list`` commands."""

import json

from click.testing import CliRunner
from osh.handlers import Env

from osh_update import core, store
from osh_update.commands import db_installed, db_update, install, list_modules, update
from osh_update.fingerprint import fingerprint_module


def _stored_fingerprints(pg_db, db_name):
    """Return the stored fingerprint map from the test database."""
    value = pg_db.query(
        db_name,
        "SELECT value FROM ir_config_parameter WHERE key = :'fp_key'",
        {"fp_key": store.FINGERPRINT_PARAM},
    )
    return json.loads(value) if value else None


def _store_fingerprints(pg_db, db_name, mapping):
    """Write *mapping* as the fingerprint param in the test database."""
    pg_db.psql(
        db_name,
        "INSERT INTO ir_config_parameter (key, value) "
        "VALUES (:'fp_key', :'fp_value')",
        {
            "fp_key": store.FINGERPRINT_PARAM,
            "fp_value": json.dumps(mapping),
        },
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
            {"compose_file": None, "dry_run": False},
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
        "INSERT INTO ir_config_parameter (key, value) "
        "VALUES (:'fp_key', 'not-json')",
        {"fp_key": store.FINGERPRINT_PARAM},
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


def test_update_fails_on_missing_db(in_project, pg_db):
    """A database that does not exist reports a clean error."""
    result = CliRunner().invoke(update, ["--db", pg_db.name()])

    assert result.exit_code != 0
    assert "does not exist" in result.output


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
            {"compose_file": None, "dry_run": True},
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
            {"compose_file": None, "dry_run": False},
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
    """--status lists tracked third-party modules and pending updates."""
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
    assert "Tracked third-party modules (2):\nmy_mod,synced_mod" in result.output
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
    assert "Tracked third-party modules (2):\n  my_mod\n  synced_mod" in result.output


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
    assert "Tracked modules (2):\nbase,my_mod" in result.output
    assert "Modules to update (1):\nmy_mod" in result.output
    assert capture_update == []


def test_update_status_first_run_baselines(
    in_project, tmp_project, module_dir, pg_db, capture_update
):
    """--status with no stored fingerprints records the baseline.

    The report lists tracked third-party modules only, but the baseline
    still covers all installed modules — otherwise a later plain
    ``osh apps update`` would flag every upstream module as changed.
    """
    db_name = pg_db.make_odoo_db(
        modules=[("my_mod", "installed"), ("base", "installed")]
    )
    module = module_dir("my_mod")
    upstream = _make_upstream_module(tmp_project)

    result = CliRunner().invoke(update, ["--db", db_name, "--status"])

    assert result.exit_code == 0
    assert "Tracked third-party modules (1):\nmy_mod\n" in result.output
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


def test_write_fingerprints_passes_payload_as_psql_variable(in_project, monkeypatch):
    """The fingerprint JSON travels via ``psql -v``, never in the SQL text."""
    captured = {}

    def fake_run(ctx, base, args, **kwargs):
        captured["args"] = args
        captured["sql"] = kwargs.get("input")
        return 0, "", ""

    monkeypatch.setattr(store, "run_in_backend", fake_run)

    mapping = {"we'ird": "deadbeef"}
    store.write_fingerprints(in_project, "db", mapping)

    payload = json.dumps(mapping, sort_keys=True)
    assert payload not in captured["sql"]
    assert f"fp_value={payload}" in captured["args"]


def test_fingerprints_roundtrip_special_values(in_project, pg_db):
    """Keys/values with quotes survive the psql-variable round trip."""
    db_name = pg_db.make_odoo_db()
    mapping = {"we'ird": 'dead"beef'}

    store.write_fingerprints(in_project, db_name, mapping)

    assert store.read_fingerprints(in_project, db_name) == mapping


# Post-restore extension ---------------------------------------------------


def _restore_op(in_project, db_name):
    """A ``backup.restore`` handler with ``RestoreBaseline`` composed in."""
    op = core.RestoreBaseline(Env(None))
    op.base = in_project
    op.db_name = db_name
    return op


def test_post_restore_records_baseline_when_absent(in_project, module_dir, pg_db):
    """A restored db without fingerprints gets a local baseline."""
    db_name = pg_db.make_odoo_db(modules=[("my_mod", "installed")])
    module = module_dir("my_mod")
    module_dir("not_installed")

    _restore_op(in_project, db_name).post_restore()

    assert _stored_fingerprints(pg_db, db_name) == {
        "my_mod": fingerprint_module(module)
    }


def test_post_restore_keeps_carried_fingerprints(in_project, module_dir, pg_db):
    """Fingerprints carried by the dump are preserved — diffs still work."""
    db_name = pg_db.make_odoo_db(modules=[("my_mod", "installed")])
    module_dir("my_mod")
    _store_fingerprints(pg_db, db_name, {"my_mod": "deadbeef"})

    _restore_op(in_project, db_name).post_restore()

    assert _stored_fingerprints(pg_db, db_name) == {"my_mod": "deadbeef"}


def test_post_restore_skips_uninitialized_db(in_project, pg_db):
    """A database without ir_module_module gets no write and no error."""
    db_name = pg_db.create()

    _restore_op(in_project, db_name).post_restore()

    assert (
        pg_db.query(
            db_name,
            "SELECT 1 FROM information_schema.tables WHERE table_schema = "
            "'public' AND table_name = 'ir_config_parameter'",
        )
        == ""
    )


def test_post_restore_baselines_active_modules_only(in_project, module_dir, pg_db):
    """The baseline covers installed/to-upgrade modules only."""
    db_name = pg_db.make_odoo_db(
        modules=[
            ("my_mod", "installed"),
            ("queued_mod", "to install"),
            ("doomed_mod", "to remove"),
        ]
    )
    module = module_dir("my_mod")
    module_dir("queued_mod")
    module_dir("doomed_mod")

    _restore_op(in_project, db_name).post_restore()

    assert _stored_fingerprints(pg_db, db_name) == {
        "my_mod": fingerprint_module(module)
    }


# ``osh apps install`` -------------------------------------------------------


def test_install_installs_and_baselines(in_project, module_dir, pg_db, capture_install):
    """``osh apps install`` runs -i, verifies the states and fingerprints.

    On an untracked database the fingerprint write is a full baseline —
    like ``osh apps update``'s first run — so the earlier-installed
    modules are not all flagged as changed afterwards.
    """
    db_name = pg_db.make_odoo_db(modules=[("base", "installed")])
    module = module_dir("my_mod")
    module_dir("other_mod")
    upstream = _make_upstream_module(in_project)

    result = CliRunner().invoke(install, ["my_mod,other_mod", "--db", db_name])

    assert result.exit_code == 0, result.output
    assert capture_install == [
        (
            ["my_mod", "other_mod"],
            db_name,
            {"compose_file": None, "dry_run": False},
        )
    ]
    assert "Installed 2 module(s)" in result.output
    assert _stored_fingerprints(pg_db, db_name) == {
        "my_mod": fingerprint_module(module),
        "other_mod": fingerprint_module(in_project / "other_mod"),
        "base": fingerprint_module(upstream),
    }


def test_install_updates_existing_fingerprints(
    in_project, module_dir, pg_db, capture_install
):
    """On a tracked database only the installed modules' entries update."""
    db_name = pg_db.make_odoo_db(modules=[("old_mod", "installed")])
    module_dir("my_mod")
    _store_fingerprints(pg_db, db_name, {"old_mod": "deadbeef"})

    result = CliRunner().invoke(install, ["my_mod", "--db", db_name])

    assert result.exit_code == 0, result.output
    assert capture_install[0][0] == ["my_mod"]
    stored = _stored_fingerprints(pg_db, db_name)
    assert stored["old_mod"] == "deadbeef"
    assert stored["my_mod"] == fingerprint_module(in_project / "my_mod")


def test_install_skips_already_installed(
    in_project, module_dir, pg_db, capture_install
):
    """Installed modules are reported and left out of the -i run."""
    db_name = pg_db.make_odoo_db(modules=[("my_mod", "installed")])
    module_dir("new_mod")

    result = CliRunner().invoke(install, ["my_mod,new_mod", "--db", db_name])

    assert result.exit_code == 0, result.output
    assert "Already installed" in result.output
    assert "my_mod" in result.output
    assert "osh apps update" in result.output
    assert capture_install == [
        (["new_mod"], db_name, {"compose_file": None, "dry_run": False})
    ]


def test_install_all_installed_is_a_noop(in_project, pg_db, capture_install):
    """Requesting only installed modules reports and runs nothing."""
    db_name = pg_db.make_odoo_db(modules=[("my_mod", "installed")])

    result = CliRunner().invoke(install, ["my_mod", "--db", db_name])

    assert result.exit_code == 0, result.output
    assert "Already installed" in result.output
    assert capture_install == []


def test_install_on_uninitialized_db(in_project, module_dir, pg_db, capture_install):
    """Installing into a database without Odoo tables bootstraps it."""
    db_name = pg_db.create()

    result = CliRunner().invoke(install, ["base", "--db", db_name])

    assert result.exit_code == 0, result.output
    assert capture_install == [
        (["base"], db_name, {"compose_file": None, "dry_run": False})
    ]


def test_install_dry_run(in_project, module_dir, pg_db, capture_install):
    """--dry-run lists the modules and runs the dry-run odoo command."""
    db_name = pg_db.make_odoo_db()
    module_dir("my_mod")

    result = CliRunner().invoke(install, ["my_mod", "--db", db_name, "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "Would install (1):\nmy_mod" in result.output
    assert capture_install == [
        (["my_mod"], db_name, {"compose_file": None, "dry_run": True})
    ]
    assert _stored_fingerprints(pg_db, db_name) is None


def test_install_reports_failure(in_project, pg_db, monkeypatch):
    """A non-zero odoo exit becomes a clear error."""
    db_name = pg_db.make_odoo_db()
    monkeypatch.setattr(core, "run_install", lambda *a, **k: 1)

    result = CliRunner().invoke(install, ["my_mod", "--db", db_name])

    assert result.exit_code != 0
    assert "odoo -i failed (exit 1)" in result.output


def test_install_detects_silent_failure(in_project, pg_db, monkeypatch):
    """A zero exit without a state change is still reported as failure."""
    db_name = pg_db.make_odoo_db(modules=[("my_mod", "uninstalled")])
    monkeypatch.setattr(core, "run_install", lambda *a, **k: 0)

    result = CliRunner().invoke(install, ["my_mod", "--db", db_name])

    assert result.exit_code != 0
    assert "were not installed" in result.output


def test_install_fails_on_missing_db(in_project, pg_db):
    """A database that does not exist reports a clean error."""
    result = CliRunner().invoke(install, ["my_mod", "--db", pg_db.name()])

    assert result.exit_code != 0
    assert "does not exist" in result.output


def test_install_requires_modules(in_project):
    result = CliRunner().invoke(install, [])
    assert result.exit_code != 0


def test_install_rejects_blank_list(in_project):
    result = CliRunner().invoke(install, [" , "])
    assert result.exit_code != 0
    assert "No module names given" in result.output


def test_install_outside_project(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(install, ["my_mod"])
    assert result.exit_code == 0
    assert "Not inside an Osh project" in result.output


# ``osh apps list`` ----------------------------------------------------------


def test_installed_lists_modules_with_version_and_state(in_project, pg_db):
    """``osh apps list`` lists non-uninstalled modules with their state."""
    db_name = pg_db.make_odoo_db(
        modules=[
            ("base", "installed", "19.0.1.0.0"),
            ("my_mod", "to upgrade", "19.0.1.0.1"),
            ("gone_mod", "uninstalled", "19.0.1.0.0"),
        ]
    )

    result = CliRunner().invoke(list_modules, ["--db", db_name])

    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert lines[0].split() == ["module", "version", "state"]
    assert any(
        all(field in line for field in ("base", "19.0.1.0.0", "installed"))
        for line in lines
    )
    assert any(
        all(field in line for field in ("my_mod", "19.0.1.0.1", "to upgrade"))
        for line in lines
    )
    assert not any("gone_mod" in line for line in lines)


def test_installed_long_adds_summary_column(in_project, pg_db):
    """``-l``/``--long`` appends the module's manifest summary."""
    db_name = pg_db.make_odoo_db(
        modules=[
            ("my_mod", "installed", "19.0.1.0.0", "My Module"),
            ("fr_mod", "installed", "19.0.1.0.0", '{"fr_FR": "Mon Module"}'),
        ]
    )

    result = CliRunner().invoke(list_modules, ["--db", db_name, "--long"])

    assert result.exit_code == 0, result.output
    assert "description" in result.output.splitlines()[0]
    assert "My Module" in result.output
    assert "Mon Module" in result.output


def test_installed_fails_on_missing_db(in_project, pg_db):
    """A database that does not exist reports a clean error."""
    result = CliRunner().invoke(list_modules, ["--db", pg_db.name()])

    assert result.exit_code != 0
    assert "does not exist" in result.output


def test_installed_rejects_non_odoo_database(in_project, pg_db):
    """A database without ``ir_module_module`` gets a clear error."""
    db_name = pg_db.create()

    result = CliRunner().invoke(list_modules, ["--db", db_name])

    assert result.exit_code != 0
    assert "not an initialized Odoo database" in result.output


def test_installed_reports_empty_registry(in_project, pg_db):
    """An Odoo database with no installed modules says so."""
    db_name = pg_db.make_odoo_db(modules=[("gone_mod", "uninstalled")])

    result = CliRunner().invoke(list_modules, ["--db", db_name])

    assert result.exit_code == 0, result.output
    assert "No modules installed" in result.output


# Deprecated ``osh db`` spellings ----------------------------------------------


def test_db_update_deprecated_warns_and_runs(
    in_project, module_dir, pg_db, capture_update
):
    """``osh db update`` warns it is deprecated and still updates."""
    db_name = pg_db.make_odoo_db(modules=[("my_mod", "installed")])
    module_dir("my_mod")
    _store_fingerprints(pg_db, db_name, {"my_mod": "deadbeef"})

    result = CliRunner().invoke(db_update, ["--db", db_name])

    assert result.exit_code == 0, result.output
    assert "'osh db update' is deprecated" in result.output
    assert "osh apps update" in result.output
    assert capture_update == [
        (
            ["my_mod"],
            db_name,
            {"compose_file": None, "dry_run": False},
        )
    ]


def test_db_installed_deprecated_warns_and_runs(in_project, pg_db):
    """``osh db installed`` warns it is deprecated and still lists."""
    db_name = pg_db.make_odoo_db(modules=[("my_mod", "installed", "1.0")])

    result = CliRunner().invoke(db_installed, ["--db", db_name])

    assert result.exit_code == 0, result.output
    assert "'osh db installed' is deprecated" in result.output
    assert "osh apps list" in result.output
    assert "my_mod" in result.output
