"""Tests for the ``osh db dump-convert`` command."""

import json
import subprocess
import zipfile

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
