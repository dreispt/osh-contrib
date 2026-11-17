"""Tests for the ``osh db dump-convert`` command."""

import json
import subprocess
import zipfile
from pathlib import Path

from click.testing import CliRunner

import osh_pgconvert.core as core
from osh_pgconvert.commands import dump_convert


def _cp(args, rc=0, stdout=b"", stderr=b""):
    return subprocess.CompletedProcess(args, rc, stdout=stdout, stderr=stderr)


def _fake_docker(args, **kwargs):
    """Stand-in for ``docker``: accepts everything, returns canned output."""
    if kwargs.get("stdout") is not None and hasattr(kwargs["stdout"], "write"):
        # Streaming call (psql restore log or pg_dump output).
        if "pg_dump" in args:
            kwargs["stdout"].write(
                b"-- fake pg_dump 16 output\n"
                b"\\restrict FAKEKEY123\n"
                b"CREATE TABLE t(id int);\n"
                b"\\unrestrict FAKEKEY123\n"
            )
        return _cp(args)
    if "pg_isready" in args:
        return _cp(args)
    if any("SHOW" in a for a in args):
        return _cp(args, stdout=b"16.14 (Debian 16.14-1.pgdg13+1)\n")
    return _cp(args)


def _make_backup(path):
    """Write a minimal Odoo-format zip backup at *path*."""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(
            "dump.sql",
            "-- dump header\n"
            "\\restrict ABC123\n"
            "CREATE TABLE res_partner(id int);\n"
            "\\unrestrict ABC123\n"
            "-- PostgreSQL database dump complete\n",
        )
        zf.writestr(
            "manifest.json",
            json.dumps(
                {
                    "odoo_dump": "1",
                    "db_name": "vinha",
                    "pg_version": "18.6",
                    "version": "19.0",
                }
            ),
        )
        zf.writestr("filestore/ab/cd", "attachment-bytes")


def test_dump_convert_repackages_backup(tmp_path, monkeypatch):
    """A user converts a PG18 Odoo backup zip for a PG16 target.

    The converted zip keeps the filestore and manifest, its dump.sql is
    the re-dumped output without \\restrict lines, and the manifest's
    pg_version reflects the target server.
    """
    src = tmp_path / "backup.zip"
    out = tmp_path / "backup-pg16.zip"
    _make_backup(src)
    monkeypatch.setattr(core, "_run", _fake_docker)
    monkeypatch.setattr(core.shutil, "which", lambda name: "/usr/bin/docker")

    result = CliRunner().invoke(dump_convert, [str(src), str(out), "--to", "16"])

    assert result.exit_code == 0, result.output
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        assert "dump.sql" in names
        assert "manifest.json" in names
        assert "filestore/ab/cd" in names
        assert zf.read("filestore/ab/cd") == b"attachment-bytes"
        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["pg_version"] == "16.14"
        assert manifest["version"] == "19.0"
        dump = zf.read("dump.sql")
    assert b"CREATE TABLE t(id int);" in dump
    assert b"\\restrict" not in dump
    assert b"\\unrestrict" not in dump


def test_dump_convert_dry_run_needs_no_docker(tmp_path, monkeypatch):
    """--dry-run reports the plan without requiring docker or running it."""
    src = tmp_path / "backup.zip"
    _make_backup(src)
    monkeypatch.setattr(core.shutil, "which", lambda name: None)  # docker absent

    result = CliRunner().invoke(dump_convert, [str(src), "--to", "16", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "postgres:16" in result.output


# --- plain SQL input -------------------------------------------------------


def test_dump_convert_accepts_plain_sql_file(tmp_path, monkeypatch):
    """A plain pg_dump -Fp .sql file converts like a zip's dump.sql.

    The output zip carries the re-dumped SQL and no manifest/filestore,
    since a bare SQL file has neither.
    """
    src = tmp_path / "dump.sql"
    src.write_text(
        "-- plain pg_dump\n"
        "\\restrict KEY1\n"
        "CREATE TABLE res_users(id int);\n"
        "\\unrestrict KEY1\n"
    )
    out = tmp_path / "dump-pg16.zip"
    monkeypatch.setattr(core, "_run", _fake_docker)
    monkeypatch.setattr(core.shutil, "which", lambda name: "/usr/bin/docker")

    result = CliRunner().invoke(dump_convert, [str(src), str(out), "--to", "16"])

    assert result.exit_code == 0, result.output
    with zipfile.ZipFile(out) as zf:
        assert "dump.sql" in zf.namelist()
        assert "manifest.json" not in zf.namelist()
        dump = zf.read("dump.sql")
    assert b"CREATE TABLE t(id int);" in dump  # re-dumped by fake pg_dump
    assert b"\\restrict" not in dump


def test_dump_convert_rejects_custom_format_dump(tmp_path):
    """A pg_dump -Fc file fails with a clear error, not a psql failure."""
    src = tmp_path / "dump.pgdump"
    src.write_bytes(b"PGDMP" + b"\x00" * 100)

    result = CliRunner().invoke(dump_convert, [str(src), "--dry-run"])

    assert result.exit_code != 0
    assert "custom" in result.output.lower() or "plain" in result.output.lower()


def test_dump_convert_filestore_flag_rejected_for_file_input(tmp_path):
    """--filestore only makes sense for a database source, not a file."""
    src = tmp_path / "backup.zip"
    _make_backup(src)

    result = CliRunner().invoke(dump_convert, [str(src), "--filestore", "--dry-run"])

    assert result.exit_code != 0


# --- project database export ----------------------------------------------


def _make_project(tmp_path, monkeypatch, name="myproject"):
    """Create a fake osh project (.osh + .git) and chdir into it."""
    project = tmp_path / name
    (project / ".osh").mkdir(parents=True)
    (project / ".git").mkdir(parents=True)
    monkeypatch.chdir(project)
    return project


def _fake_db_backend(monkeypatch, modules=None, filestore_dir=None):
    """Stub the osh.db helpers used by DB export; fake docker still runs."""
    monkeypatch.setattr(core, "_run", _fake_docker)
    monkeypatch.setattr(core.shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(core, "db_exists", lambda *a, **k: True)

    def fake_run_in_runtime(ctx, base, argv, **kwargs):
        if "pg_dump" in argv:
            kwargs["stdout"].write(
                b"-- pg_dump of project db\nCREATE TABLE ir_module_module(id int);\n"
            )
        return 0, "", ""

    monkeypatch.setattr(core, "run_in_runtime", fake_run_in_runtime)
    monkeypatch.setattr(
        core,
        "psql_rows",
        lambda *a, **k: (
            0,
            modules if modules is not None else [["base", "19.0.1.0"]],
            "",
        ),
    )
    monkeypatch.setattr(
        core,
        "filestore_path",
        lambda base, db: str(filestore_dir) if filestore_dir else None,
    )


def test_dump_convert_from_db_exports_project_database(tmp_path, monkeypatch):
    """--from-db dumps the named database through the project runtime and
    produces an Odoo zip with a synthesized manifest (incl. modules)."""
    _make_project(tmp_path, monkeypatch)
    _fake_db_backend(monkeypatch, modules=[["base", "19.0.1.0"], ["sale", "1.0"]])
    out = tmp_path / "export.zip"

    result = CliRunner().invoke(
        dump_convert, ["--from-db", "vinha", str(out), "--to", "16"]
    )

    assert result.exit_code == 0, result.output
    with zipfile.ZipFile(out) as zf:
        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["odoo_dump"] == "1"
        assert manifest["db_name"] == "vinha"
        assert manifest["modules"] == {"base": "19.0.1.0", "sale": "1.0"}
        assert manifest["pg_version"] == "16.14"
        assert "filestore/" not in " ".join(zf.namelist())
        assert b"CREATE TABLE t(id int);" in zf.read("dump.sql")


def test_dump_convert_no_args_uses_project_database(tmp_path, monkeypatch):
    """Inside a project with no INPUT and no --from-db, the project's
    resolved database is exported; output defaults to <db>-pg<to>.zip."""
    project = _make_project(tmp_path, monkeypatch, name="myproject")
    _fake_db_backend(monkeypatch)
    monkeypatch.chdir(project)

    result = CliRunner().invoke(dump_convert, ["--to", "16"])

    assert result.exit_code == 0, result.output
    # resolve_db_name generates "<project>-<branch>"; no real git repo →
    # branch falls back to "default". Output defaults to cwd.
    expected = project / "myproject-default-pg16.zip"
    assert expected.exists(), list(project.iterdir())


def test_dump_convert_from_db_rejects_two_output_paths(tmp_path, monkeypatch):
    """With --from-db there is no input, so only one positional (the
    output path) is allowed."""
    _make_project(tmp_path, monkeypatch)

    result = CliRunner().invoke(
        dump_convert,
        ["--from-db", "vinha", "a.zip", "b.zip", "--dry-run"],
    )

    assert result.exit_code != 0
    assert "output" in result.output.lower()


def test_dump_convert_db_mode_outside_project_errors(tmp_path, monkeypatch):
    """--from-db requires an osh project (runtime + PG config live there)."""
    monkeypatch.chdir(tmp_path)  # no .osh anywhere up the tree? ensure none
    result = CliRunner().invoke(dump_convert, ["--from-db", "vinha", "--dry-run"])
    assert result.exit_code != 0


def test_dump_convert_no_args_outside_project_errors(tmp_path, monkeypatch):
    """No INPUT, no --from-db, no project → actionable error."""
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(dump_convert, [])

    assert result.exit_code != 0
    assert "project" in result.output.lower() or "input" in result.output.lower()


def test_dump_convert_missing_database_errors_cleanly(tmp_path, monkeypatch):
    """--from-db on a nonexistent database fails before docker runs."""
    _make_project(tmp_path, monkeypatch)
    _fake_db_backend(monkeypatch)
    monkeypatch.setattr(core, "db_exists", lambda *a, **k: False)

    result = CliRunner().invoke(
        dump_convert, ["--from-db", "ghost", str(tmp_path / "o.zip")]
    )

    assert result.exit_code != 0
    assert "ghost" in result.output


def test_dump_convert_filestore_included_for_db_export(tmp_path, monkeypatch):
    """--filestore copies the project filestore into the output zip."""
    _make_project(tmp_path, monkeypatch)
    filestore = tmp_path / "filestore"
    (filestore / "ab").mkdir(parents=True)
    (filestore / "ab" / "cd").write_bytes(b"attachment-bytes")
    _fake_db_backend(monkeypatch, filestore_dir=filestore)
    out = tmp_path / "export.zip"

    result = CliRunner().invoke(
        dump_convert,
        ["--from-db", "vinha", str(out), "--to", "16", "--filestore"],
    )

    assert result.exit_code == 0, result.output
    with zipfile.ZipFile(out) as zf:
        assert zf.read("filestore/ab/cd") == b"attachment-bytes"


def test_dump_convert_filestore_skipped_when_unavailable(tmp_path, monkeypatch):
    """--filestore on a runtime without a host filestore warns, not fails."""
    _make_project(tmp_path, monkeypatch)
    _fake_db_backend(monkeypatch, filestore_dir=None)  # filestore_path → None
    out = tmp_path / "export.zip"

    result = CliRunner().invoke(
        dump_convert,
        ["--from-db", "vinha", str(out), "--to", "16", "--filestore"],
    )

    assert result.exit_code == 0, result.output
    with zipfile.ZipFile(out) as zf:
        assert not any(n.startswith("filestore/") for n in zf.namelist())


def test_dump_convert_db_dry_run_needs_no_docker(tmp_path, monkeypatch):
    """--from-db --dry-run prints the plan without docker or pg_dump."""
    _make_project(tmp_path, monkeypatch)
    monkeypatch.setattr(core.shutil, "which", lambda name: None)
    monkeypatch.setattr(core, "db_exists", lambda *a, **k: True)

    result = CliRunner().invoke(
        dump_convert, ["--from-db", "vinha", "--to", "16", "--dry-run"]
    )

    assert result.exit_code == 0, result.output
    assert "vinha" in result.output
    assert "postgres:16" in result.output


# --- PG18 syntax downgrade -------------------------------------------------


def test_dump_convert_rewrites_pg18_not_null_constraints(tmp_path, monkeypatch):
    """A PG18 dump using named NOT NULL table constraints converts to PG16.

    PG18 dumps ``CONSTRAINT name NOT NULL col`` / bare ``NOT NULL col``
    as table elements (e.g. on ir_act_* tables inheriting ir_actions);
    PG<=17 rejects that syntax, so the converter must move the
    constraint into an ALTER TABLE after the CREATE TABLE.
    """
    src = tmp_path / "backup.zip"
    out = tmp_path / "backup-pg16.zip"
    with zipfile.ZipFile(src, "w") as zf:
        zf.writestr(
            "dump.sql",
            "CREATE TABLE public.ir_actions (\n"
            "    id integer NOT NULL,\n"
            "    name jsonb NOT NULL\n"
            ");\n"
            "CREATE TABLE public.ir_act_server (\n"
            "    CONSTRAINT ir_actions_name_not_null NOT NULL name,\n"
            "    code text\n"
            ")\n"
            "INHERITS (public.ir_actions);\n"
            "CREATE TABLE public.ir_act_window (\n"
            "    NOT NULL name,\n"
            "    view_id integer\n"
            ")\n"
            "INHERITS (public.ir_actions);\n"
            "COPY public.ir_act_server (id, name, code) FROM stdin;\n"
            "1\t{}\t-x-\n"
            "\\.\n",
        )
    staged = {}

    def fake(args, **kwargs):
        if args[0] == "cp":
            staged["dump"] = Path(args[1]).read_bytes()
        return _fake_docker(args, **kwargs)

    monkeypatch.setattr(core, "_run", fake)
    monkeypatch.setattr(core.shutil, "which", lambda name: "/usr/bin/docker")

    result = CliRunner().invoke(dump_convert, [str(src), str(out), "--to", "16"])

    assert result.exit_code == 0, result.output
    dump_in = staged["dump"]
    assert b"CONSTRAINT ir_actions_name_not_null NOT NULL name" not in dump_in
    assert (
        b"ALTER TABLE ONLY public.ir_act_server ALTER COLUMN name SET NOT NULL;"
        in dump_in
    )
    assert (
        b"ALTER TABLE ONLY public.ir_act_window ALTER COLUMN name SET NOT NULL;"
        in dump_in
    )
    # COPY payload must pass through untouched
    assert b"1\t{}\t-x-" in dump_in
