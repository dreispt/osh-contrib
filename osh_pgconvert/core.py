"""Convert a PostgreSQL dump to a different server major version.

The conversion itself is delegated to the ``pgdump-convert`` package
(https://github.com/OdooEssentials/pgdump-convert): it restores the dump
into a throwaway ``postgres:<version>`` docker container and re-dumps
from that server. This module keeps the osh-specific parts — dumping a
project database through its runtime and bundling its filestore — and
stages the result as an Odoo-format zip for ``pgdump_convert``.
"""

import json
import shutil
import tempfile
import zipfile
from pathlib import Path

import click
from osh import echo
from osh.db import db_exists, filestore_path, psql_rows, run_in_runtime

PGDUMP_CONVERT_INSTALL = """\
pgdump-convert is required for 'osh db dump-convert' but is not installed.

Install it into osh's environment with:

    pipx inject osh "pgdump-convert @ git+https://github.com/OdooEssentials/pgdump-convert.git"

For a venv or uv install, use that environment's installer instead:

    pip install "pgdump-convert @ git+https://github.com/OdooEssentials/pgdump-convert.git"
"""


def _pgdump_convert():
    """Import ``pgdump_convert.core`` or fail with install instructions."""
    try:
        from pgdump_convert import core as pgc
    except ImportError as exc:
        raise click.ClickException(PGDUMP_CONVERT_INSTALL) from exc
    return pgc


def convert(
    src,
    output,
    image="postgres:16",
    db_name="odoo",
    dry_run=False,
    allow_restore_errors=False,
):
    """Convert *src* (Odoo zip backup, plain SQL dump, or ``-`` for stdin).

    Delegates to ``pgdump_convert.core.convert``; *output* may be ``-``
    for stdout.
    """
    src = str(src)
    output = str(output)
    if dry_run:
        echo.info(
            f"Would restore {src} into a throwaway {image} container "
            f"and write {output}",
            err=True,
        )
        return
    pgc = _pgdump_convert()
    pgc.convert(
        src,
        output,
        image=image,
        db_name=db_name,
        dry_run=False,
        allow_restore_errors=allow_restore_errors,
    )


def _dump_db(ctx, base, src_db, out_path):
    """pg_dump *src_db* as plain SQL into *out_path* via the project runtime."""
    with open(out_path, "wb") as f:
        returncode, _, stderr = run_in_runtime(
            ctx,
            base,
            ["pg_dump", "-Fp", "--no-owner", "-d", src_db],
            stdout=f,
            text=False,
        )
    if returncode is None:
        raise click.ClickException(
            "Could not locate `pg_dump`. Is PostgreSQL installed?"
        )
    if returncode != 0:
        if isinstance(stderr, bytes):
            stderr = stderr.decode(errors="replace")
        raise click.ClickException(f"pg_dump failed: {stderr[:500]}")


def _copy_filestore(ctx, base, src_db, work):
    """Copy the project's filestore into ``work/filestore`` when readable."""
    path = filestore_path(base, src_db)
    src = Path(path) if path else None
    if src is None or not src.is_dir():
        echo.warning(
            f"filestore for '{src_db}' is not readable on this host "
            "(container runtimes keep it inside the container); skipping",
            err=True,
        )
        return
    shutil.copytree(src, work / "filestore")


def _write_source_manifest(ctx, base, src_db, work):
    """Synthesize an Odoo-style manifest.json for a live database export.

    ``modules`` comes from ``ir_module_module``; version fields that only
    the Odoo server knows are left out rather than invented.
    """
    manifest = {"odoo_dump": "1", "db_name": src_db, "modules": {}}
    returncode, rows, _ = psql_rows(
        base,
        src_db,
        "SELECT name, latest_version FROM ir_module_module "
        "WHERE state = 'installed'",
        ctx=ctx,
    )
    if returncode == 0:
        manifest["modules"] = {row[0]: row[1] for row in rows if len(row) >= 2}
    (work / "manifest.json").write_text(json.dumps(manifest, indent=4))


def _stage_zip(work, staged):
    """Pack ``work/{dump.sql,manifest.json,filestore/}`` into *staged*."""
    with zipfile.ZipFile(staged, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(work / "dump.sql", "dump.sql")
        manifest = work / "manifest.json"
        if manifest.exists():
            zf.write(manifest, "manifest.json")
        filestore = work / "filestore"
        if filestore.exists():
            for path in sorted(filestore.rglob("*")):
                if path.is_file():
                    zf.write(
                        path,
                        "filestore/" + path.relative_to(filestore).as_posix(),
                    )


def convert_db(
    ctx,
    base,
    src_db,
    output,
    image="postgres:16",
    db_name="odoo",
    include_filestore=False,
    dry_run=False,
    allow_restore_errors=False,
):
    """Export database *src_db* through the project's runtime and convert it.

    *base* is the osh project root; the dump and filestore are read via
    the project's configured runtime, staged as an Odoo-format zip, then
    converted by ``pgdump_convert`` like any other input.
    """
    output = str(output)
    if dry_run:
        echo.info(
            f"Would pg_dump '{src_db}' and write {output} via a throwaway "
            f"{image} container",
            err=True,
        )
        if include_filestore:
            echo.info("Would include the project filestore", err=True)
        return
    pgc = _pgdump_convert()
    if not db_exists(base, src_db, ctx=ctx):
        raise click.ClickException(f"database '{src_db}' does not exist")
    # Work next to a real output dir (or cwd for stdout): /tmp is often a
    # small tmpfs and dumps are huge.
    anchor = Path.cwd() if output == "-" else Path(output).parent
    if output != "-":
        anchor.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=anchor) as tmp:
        work = Path(tmp)
        echo.info(f"dumping '{src_db}'")
        _dump_db(ctx, base, src_db, work / "dump.sql")
        if include_filestore:
            _copy_filestore(ctx, base, src_db, work)
        _write_source_manifest(ctx, base, src_db, work)
        staged = work / "input.zip"
        _stage_zip(work, staged)
        pgc.convert(
            str(staged),
            output,
            image=image,
            db_name=db_name,
            dry_run=False,
            allow_restore_errors=allow_restore_errors,
        )


__all__ = ["convert", "convert_db"]
