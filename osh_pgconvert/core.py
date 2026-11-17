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

RESTRICT_RE = re.compile(rb"^\\(?:un)?restrict [A-Za-z0-9]+\s*$")


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


def _strip_restrict(data):
    """Drop \\restrict/\\unrestrict lines (psql <17.6 cannot parse them)."""
    return b"".join(
        line for line in data.splitlines(keepends=True) if not RESTRICT_RE.match(line)
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
        if line.startswith("ERROR")
    ]
    echo.info(f"psql reported {len(errors)} ERROR line(s)")
    for line in errors[-5:]:
        echo.warning(f"  {line}")


def _redump(container, db_name, out_path):
    """pg_dump from the container into *out_path*; return server_version."""
    with open(out_path, "wb") as f:
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
    out_path.write_bytes(_strip_restrict(out_path.read_bytes()))
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


def convert(zip_path, output, image="postgres:16", db_name="odoo", dry_run=False):
    """Convert *zip_path* into a dump compatible with *image*'s PostgreSQL."""
    zip_path = Path(zip_path)
    output = Path(output)
    if not zipfile.is_zipfile(zip_path):
        raise click.ClickException(f"{zip_path} is not a zip backup")
    if dry_run:
        echo.info(
            f"Would restore {zip_path} into a throwaway {image} container "
            f"and write {output}",
            err=True,
        )
        return
    if shutil.which("docker") is None:
        raise click.ClickException("docker not found on PATH")
    container = f"osh-pgconvert-{os.getpid()}"
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        _extract(zip_path, work)
        dump_in = work / "dump-in.sql"
        dump_in.write_bytes(_strip_restrict((work / "dump.sql").read_bytes()))

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
            server_version = _redump(container, db_name, work / "dump-new.sql")
        finally:
            _run(["rm", "-f", container])
        echo.info(f"server_version: {server_version}")
        _write_zip(work, output, server_version)


__all__ = ["convert"]
