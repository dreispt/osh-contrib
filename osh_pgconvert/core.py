"""Convert a PostgreSQL dump to a different server major version.

The SQL version conversion is delegated to the ``pgdump-convert``
package (https://github.com/OdooEssentials/pgdump-convert). This module
owns the Odoo side: extracting and repacking backup zips, carrying
``manifest.json`` and ``filestore/``, and dumping project databases
through the osh runtime.
"""

import json
import shutil
import sys
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

__all__ = ["convert", "convert_db"]


def convert(
    src,
    output,
    image="postgres:16",
    db_name="odoo",
    docker=None,
    target_version=None,
    dry_run=False,
    allow_restore_errors=False,
):
    """Convert *src* (Odoo zip backup, plain SQL dump, or ``-`` for stdin).

    The SQL is converted by ``pgdump_convert``; the result is repacked
    as an Odoo-format zip at *output* (``-`` for stdout on stdout.buffer).
    """
    src = str(src)
    output = str(output)
    if dry_run:
        echo.info(f"Would convert {src} and write {output}", err=True)
        if docker:
            echo.info(
                f"Would load into a throwaway {image} container ({docker})",
                err=True,
            )
        return
    pgc = _pgdump_convert()
    # Work next to a real output dir (or cwd for stdout): /tmp is often a
    # small tmpfs and dumps are huge.
    anchor = Path.cwd() if output == "-" else Path(output).parent
    if output != "-":
        anchor.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=anchor) as tmp:
        work = Path(tmp)
        sql_path = _stage_input(src, work)
        _convert_sql(
            pgc,
            sql_path,
            work,
            output,
            image,
            db_name,
            docker,
            target_version,
            allow_restore_errors,
        )


def convert_db(
    ctx,
    base,
    src_db,
    output,
    image="postgres:16",
    db_name="odoo",
    include_filestore=False,
    docker=None,
    target_version=None,
    dry_run=False,
    allow_restore_errors=False,
):
    """Export database *src_db* through the project's runtime and convert it.

    *base* is the osh project root; the dump is read via the project's
    configured runtime, converted by ``pgdump_convert``, and repacked
    with a synthesized manifest (and the filestore when requested) as an
    Odoo-format zip at *output*.
    """
    output = str(output)
    if dry_run:
        echo.info(
            f"Would pg_dump '{src_db}' and write {output}",
            err=True,
        )
        if include_filestore:
            echo.info("Would include the project filestore", err=True)
        if docker:
            echo.info(
                f"Would load into a throwaway {image} container ({docker})",
                err=True,
            )
        return
    pgc = _pgdump_convert()
    if not db_exists(base, src_db, ctx=ctx):
        raise click.ClickException(f"database '{src_db}' does not exist")
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
        _convert_sql(
            pgc,
            work / "dump.sql",
            work,
            output,
            image,
            db_name,
            docker,
            target_version,
            allow_restore_errors,
        )


def _pgdump_convert():
    """Import ``pgdump_convert.core`` or fail with install instructions."""
    try:
        from pgdump_convert import core as pgc
    except ImportError as exc:
        raise click.ClickException(PGDUMP_CONVERT_INSTALL) from exc
    return pgc


def _stage_input(src, work):
    """Stage *src* and return the path of the plain SQL dump.

    *src* may be ``"-"`` (stdin), an Odoo zip backup, or a plain SQL
    file. Zip contents (``dump.sql``, ``manifest.json``, ``filestore/``)
    are extracted into *work*; anything else is rejected later by
    ``pgdump_convert`` itself.
    """
    if src == "-":
        staged = work / "input.bin"
        echo.info("reading dump from stdin", err=True)
        with open(staged, "wb") as f:
            shutil.copyfileobj(sys.stdin.buffer, f)
        path = staged
    else:
        path = Path(src)
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as zf:
            for name in zf.namelist():
                if (
                    name == "dump.sql"
                    or name == "manifest.json"
                    or name.startswith("filestore/")
                ):
                    zf.extract(name, work)
        if not (work / "dump.sql").exists():
            raise click.ClickException(f"{src} does not contain dump.sql")
        return work / "dump.sql"
    return path


def _write_zip(work, output, dump_sql, pg_version):
    """Repack ``dump.sql`` + ``manifest.json`` + ``filestore/`` into *output*.

    *output* may be ``"-"`` for stdout (binary zip on stdout.buffer).
    """
    manifest_path = work / "manifest.json"
    manifest = None
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
    if manifest:
        if pg_version:
            manifest["pg_version"] = pg_version
        manifest_path.write_text(json.dumps(manifest, indent=4))
    to_stdout = output == "-"
    target = work / "output.zip" if to_stdout else Path(output)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        if manifest:
            zf.write(manifest_path, "manifest.json")
        filestore = work / "filestore"
        if filestore.exists():
            for path in sorted(filestore.rglob("*")):
                if path.is_file():
                    zf.write(
                        path,
                        "filestore/" + path.relative_to(filestore).as_posix(),
                    )
        zf.write(dump_sql, "dump.sql")
    if to_stdout:
        with open(target, "rb") as f:
            shutil.copyfileobj(f, sys.stdout.buffer)
        echo.info("wrote zip to stdout", err=True)
    else:
        echo.info(f"wrote {output}", err=True)


def _convert_sql(
    pgc,
    sql_path,
    work,
    output,
    image,
    db_name,
    docker,
    target_version,
    allow_restore_errors,
):
    """Run pgdump_convert on *sql_path* and repack the Odoo zip."""
    converted = work / "converted.sql"
    pgc.convert(
        str(sql_path),
        str(converted),
        image=image,
        db_name=db_name,
        docker=docker,
        dry_run=False,
        allow_restore_errors=allow_restore_errors,
    )
    _write_zip(work, output, converted, target_version)


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
