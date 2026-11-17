"""Convert a PostgreSQL dump to a different server major version."""

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path

import click
from osh import echo
from osh.db import db_exists, filestore_path, psql_rows, run_in_runtime

RESTRICT_RE = re.compile(rb"^\\(?:un)?restrict [A-Za-z0-9]+\s*$")
# PG18 emits NOT NULL as named table constraints; PG<=17 rejects them.
PG18_NOT_NULL_RE = re.compile(
    rb'^\s*(?:CONSTRAINT\s+\w+\s+)?NOT\s+NULL\s+("[^"]+"|\w+),?\s*$'
)
SET_TIMEOUT_RE = re.compile(rb"^SET\s+transaction_timeout\s*=")
COPY_RE = re.compile(rb"^COPY\s")
CREATE_TABLE_RE = re.compile(
    rb"^CREATE\s+(?:UNLOGGED\s+|TEMP(?:ORARY)?\s+)?TABLE\s+(?:IF NOT EXISTS\s+)?"
    rb'((?:"[^"]+"|[\w]+)(?:\.(?:"[^"]+"|[\w]+))?)\s*\('
)


def _run(args, *, capture=True, **kwargs):
    """Run ``docker <args>`` and return the CompletedProcess."""
    if capture:
        kwargs["capture_output"] = True
    return subprocess.run(["docker", *args], check=False, **kwargs)


def _docker_exec(container, args, **kwargs):
    return _run(["exec", container, *args], **kwargs)


def _extract(zip_path, work):
    """Extract dump.sql, manifest.json and filestore/ from the backup zip."""
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            if (
                name == "dump.sql"
                or name == "manifest.json"
                or name.startswith("filestore/")
            ):
                zf.extract(name, work)
    if not (work / "dump.sql").exists():
        raise click.ClickException(f"{zip_path} does not contain dump.sql")


def _import_sql(path, work):
    """Stage a plain-SQL dump file as ``work/dump.sql``.

    Custom-format dumps (``PGDMP`` magic) are rejected: they cannot be
    fed to ``psql`` and newer ``pg_restore`` refuses older-format files
    anyway, so they are outside what this command can convert.
    """
    with open(path, "rb") as f:
        magic = f.read(5)
    if magic == b"PGDMP":
        raise click.ClickException(
            f"{path} is a custom-format pg_dump; dump-convert needs "
            "plain SQL (pg_dump -Fp) or an Odoo zip backup"
        )
    shutil.copyfile(path, work / "dump.sql")


def _filter_dump(src, dst):
    """Copy *src* to *dst* making it importable by older PostgreSQL clients.

    Streams line by line so multi-GB dumps don't exhaust memory. Drops:

    - ``\\restrict``/``\\unrestrict`` meta-commands (psql <17.6);
    - ``SET transaction_timeout`` (GUC added in PG17);
    - PG18 table-level ``[CONSTRAINT name] NOT NULL col`` elements, which
      are rewritten as ``ALTER TABLE ... ALTER COLUMN ... SET NOT NULL``
      after the CREATE TABLE (PG<=17 rejects the inline syntax).
    """
    dropped_nn = 0
    in_copy = False
    table_buf = None
    table_name = None
    nn_cols = []
    with open(src, "rb") as fin, open(dst, "wb") as fout:
        for line in fin:
            if in_copy:
                fout.write(line)
                if line.rstrip(b"\r\n") == b"\\.":
                    in_copy = False
                continue
            if table_buf is not None:
                table_buf.append(line)
                if not line.rstrip().endswith(b";"):
                    continue
                for buf_line in table_buf:
                    m = PG18_NOT_NULL_RE.match(buf_line)
                    if m:
                        nn_cols.append(m.group(1))
                        dropped_nn += 1
                        continue
                    fout.write(buf_line)
                for col in nn_cols:
                    fout.write(
                        b"ALTER TABLE ONLY "
                        + table_name
                        + b" ALTER COLUMN "
                        + col
                        + b" SET NOT NULL;\n"
                    )
                table_buf = None
                nn_cols = []
                continue
            if RESTRICT_RE.match(line) or SET_TIMEOUT_RE.match(line):
                continue
            if COPY_RE.match(line):
                in_copy = True
            m = CREATE_TABLE_RE.match(line)
            if m:
                table_buf = [line]
                table_name = m.group(1)
                if line.rstrip().endswith(b";"):
                    # single-line CREATE TABLE — flush immediately
                    for buf_line in table_buf:
                        fout.write(buf_line)
                    table_buf = None
                continue
            fout.write(line)
    if dropped_nn:
        echo.warning(
            f"rewrote {dropped_nn} PG18 NOT NULL table constraint(s) "
            "as ALTER TABLE ... SET NOT NULL"
        )


def _wait_ready(container):
    for _ in range(60):
        result = _docker_exec(container, ["pg_isready", "-U", "postgres"])
        if result.returncode == 0:
            return
        time.sleep(1)
    raise click.ClickException(f"container {container} did not become ready")


def _restore(container, db_name, dump_file, log_path):
    _run(["cp", str(dump_file), f"{container}:/tmp/dump.sql"])
    with open(log_path, "wb") as log:
        _docker_exec(
            container,
            ["psql", "-U", "postgres", "-d", db_name, "-f", "/tmp/dump.sql"],
            capture=False,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    errors = [
        line
        for line in log_path.read_text(errors="replace").splitlines()
        if "ERROR:" in line
    ]
    echo.info(f"psql reported {len(errors)} ERROR line(s)")
    for line in errors[-5:]:
        echo.warning(f"  {line}")


def _redump(container, db_name, raw_path, out_path):
    """pg_dump from the container; return server_version.

    Raw output goes to *raw_path*, then is streamed through
    ``_strip_restrict`` into *out_path*.
    """
    with open(raw_path, "wb") as f:
        result = _docker_exec(
            container,
            ["pg_dump", "-Fp", "--no-owner", "-U", "postgres", db_name],
            capture=False,
            stdout=f,
            stderr=subprocess.PIPE,
        )
    if result.returncode != 0:
        raise click.ClickException(
            f"pg_dump failed: {result.stderr.decode(errors='replace')[:500]}"
        )
    # The container's pg_dump may itself emit \restrict (>=16.15); strip it.
    _filter_dump(raw_path, out_path)
    raw_path.unlink()
    result = _docker_exec(
        container,
        ["psql", "-U", "postgres", "-tA", "-c", "SHOW server_version"],
    )
    return result.stdout.decode().strip().split()[0]


def _write_zip(work, output, pg_version):
    """Repack dump.sql + filestore/ + manifest.json into the output zip."""
    manifest_path = work / "manifest.json"
    manifest = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
    if manifest:
        manifest["pg_version"] = pg_version
        manifest_path.write_text(json.dumps(manifest, indent=4))
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
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
        zf.write(work / "dump-new.sql", "dump.sql")
    echo.success(f"wrote {output}")


def _convert_work(work, output, image, db_name, container):
    """Run the throwaway-container conversion on ``work/dump.sql``.

    ``work`` may also hold ``manifest.json`` and ``filestore/``; they are
    preserved into the output zip by ``_write_zip``.
    """
    dump_in = work / "dump-in.sql"
    _filter_dump(work / "dump.sql", dump_in)
    (work / "dump.sql").unlink()

    echo.info(f"starting throwaway {image} container")
    result = _run(
        [
            "run",
            "-d",
            "--name",
            container,
            "-e",
            "POSTGRES_HOST_AUTH_METHOD=trust",
            image,
        ]
    )
    if result.returncode != 0:
        raise click.ClickException(
            f"docker run failed: {result.stderr.decode(errors='replace')[:300]}"
        )
    try:
        _wait_ready(container)
        _docker_exec(container, ["createdb", "-U", "postgres", db_name])
        echo.info("restoring dump")
        _restore(container, db_name, dump_in, work / "psql.log")
        echo.info(f"re-dumping with pg_dump from {image}")
        server_version = _redump(
            container, db_name, work / "dump-raw.sql", work / "dump-new.sql"
        )
    finally:
        _run(["rm", "-f", container])
    echo.info(f"server_version: {server_version}")
    _write_zip(work, output, server_version)


def convert(zip_path, output, image="postgres:16", db_name="odoo", dry_run=False):
    """Convert *zip_path* (Odoo zip backup or plain SQL dump).

    The input is staged as ``dump.sql`` — the plain-SQL format Odoo zip
    backups use — then restored into a throwaway container running
    *image*'s PostgreSQL and re-dumped from that server.
    """
    zip_path = Path(zip_path)
    output = Path(output)
    is_zip = zipfile.is_zipfile(zip_path)
    if not is_zip:
        with open(zip_path, "rb") as f:
            is_custom = f.read(5) == b"PGDMP"
    else:
        is_custom = False
    if is_custom:
        raise click.ClickException(
            f"{zip_path} is a custom-format pg_dump; dump-convert needs "
            "plain SQL (pg_dump -Fp) or an Odoo zip backup"
        )
    if dry_run:
        echo.info(
            f"Would restore {zip_path} into a throwaway {image} container "
            f"and write {output}",
            err=True,
        )
        return
    if shutil.which("docker") is None:
        raise click.ClickException("docker not found on PATH")
    output.parent.mkdir(parents=True, exist_ok=True)
    container = f"osh-pgconvert-{os.getpid()}"
    # Work next to the output: /tmp is often a small tmpfs and dumps are huge.
    with tempfile.TemporaryDirectory(dir=output.parent) as tmp:
        work = Path(tmp)
        if is_zip:
            _extract(zip_path, work)
        else:
            _import_sql(zip_path, work)
        _convert_work(work, output, image, db_name, container)


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


def convert_db(
    ctx,
    base,
    src_db,
    output,
    image="postgres:16",
    db_name="odoo",
    include_filestore=False,
    dry_run=False,
):
    """Export database *src_db* through the project's runtime and convert it.

    *base* is the osh project root; the dump and filestore are read via
    the project's configured runtime, then go through the same
    throwaway-container conversion as file input.
    """
    output = Path(output)
    if dry_run:
        echo.info(
            f"Would pg_dump '{src_db}' and write {output} via a throwaway "
            f"{image} container",
            err=True,
        )
        if include_filestore:
            echo.info("Would include the project filestore", err=True)
        return
    if shutil.which("docker") is None:
        raise click.ClickException("docker not found on PATH")
    if not db_exists(base, src_db, ctx=ctx):
        raise click.ClickException(f"database '{src_db}' does not exist")
    output.parent.mkdir(parents=True, exist_ok=True)
    container = f"osh-pgconvert-{os.getpid()}"
    with tempfile.TemporaryDirectory(dir=output.parent) as tmp:
        work = Path(tmp)
        echo.info(f"dumping '{src_db}'")
        _dump_db(ctx, base, src_db, work / "dump.sql")
        if include_filestore:
            _copy_filestore(ctx, base, src_db, work)
        _write_source_manifest(ctx, base, src_db, work)
        _convert_work(work, output, image, db_name, container)


__all__ = ["convert", "convert_db"]
