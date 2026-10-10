"""Install/update orchestration for ``osh apps install``/``osh apps update``.

Detects which installed project modules changed since the last update and
runs ``odoo -u`` on them through the public ``osh odoo`` CLI; installs
modules with ``odoo -i``. Kept separate from the Click commands so it can
be reused and monkeypatched in tests. Also hosts the ``backup.restore``
``post_restore`` extension that fingerprints freshly restored databases.
"""

import subprocess
import sys
import time

import click
from osh import echo
from osh.handlers import resolve

from . import store
from .fingerprint import (
    discover_modules,
    fingerprint_modules_by_name,
    fingerprint_project_modules,
)


def detect_targets(
    base,
    db_name,
    *,
    update_all=False,
    status=False,
    dry_run=False,
    skip_nested=False,
    per_line=False,
    ctx=None,
):
    """Compute and report which installed project modules need an update.

    Returns the module list to pass to ``-u``, or ``None`` when nothing
    should run — a fingerprint baseline was recorded (first run), or
    *status* report mode was used.
    """
    states = store.get_module_states(base, db_name, ctx=ctx)
    if states is None:
        raise click.ClickException(
            f"Database '{db_name}' is not initialized. Install modules first "
            f"(e.g. 'osh apps install base -d {db_name}')."
        )

    if update_all and not status:
        third_party = fingerprint_project_modules(
            base, skip_nested=skip_nested, upstream=False
        )
        return sorted(n for n in third_party if states.get(n) in store.ACTIVE_STATES)

    current = fingerprint_project_modules(base, skip_nested=skip_nested)
    stored = store.read_fingerprints(base, db_name, ctx=ctx)

    known = set(current) | set(stored or {})
    installed = {n for n in known if states.get(n) in store.ACTIVE_STATES}

    # In status mode --all widens the report to upstream modules; without
    # it only third-party modules are reported. The fingerprint baseline
    # still covers all installed modules, upstream included.
    reported = installed
    if status and not update_all:
        reported = installed & set(
            discover_modules(base, skip_nested=skip_nested, upstream=False)
        )

    if status:
        label = "Tracked modules" if update_all else "Tracked third-party modules"
        _report_module_list(label, sorted(reported), per_line=per_line)

    for name in sorted(reported - set(current)):
        echo.warning(
            f"Module '{name}' is installed in the database but no "
            "longer on disk; update or uninstall it manually."
        )

    if stored is None:
        if dry_run:
            echo.info(
                f"Would record baseline fingerprints for {len(installed)} "
                "module(s); no updates would run."
            )
        else:
            baseline = _baseline_mapping(current, states)
            store.write_fingerprints(base, db_name, baseline, ctx=ctx)
            echo.success(
                f"Recorded baseline fingerprints for {len(baseline)} "
                "module(s); no updates run."
            )
            echo.info(
                "Run 'osh apps update --all' to force-update installed "
                "third-party modules."
            )
        return None

    changed = sorted(
        n for n in reported if n in current and stored.get(n) != current[n]
    )
    if status:
        _report_module_list("Modules to update", changed, per_line=per_line)
        return None
    return changed


class RestoreBaseline(resolve("backup.restore")):
    """Extends ``osh backup restore`` — baseline restored dbs lacking one.

    A restored dump keeps the fingerprint map it carried — it describes the
    code the database was last updated against, so real diffs are still
    detected by the next ``osh apps update``. Only when the dump has no map
    at all are the local modules' fingerprints recorded, so subsequent runs
    diff from the restore point instead of re-baselining lazily.

    The extension signature carries no options, so the baseline always uses
    the default fingerprint scope — nested repos included, like a plain
    ``osh apps update``. ``--no-submodules`` only narrows what a later
    update run compares, never what the restore recorded.
    """

    def post_restore(self):
        super().post_restore()
        states = store.get_module_states(self.base, self.db_name, ctx=self.ctx)
        if states is None:
            return
        if store.read_fingerprints(self.base, self.db_name, ctx=self.ctx) is not None:
            return
        baseline = _baseline_mapping(fingerprint_project_modules(self.base), states)
        store.write_fingerprints(self.base, self.db_name, baseline, ctx=self.ctx)
        # Restore output goes to stderr, so this joins it rather than stdout.
        echo.success(
            f"Recorded baseline fingerprints for {len(baseline)} module(s).",
            err=True,
        )


def _baseline_mapping(current, states):
    """Return the ``{module: digest}`` baseline for modules active in *states*."""
    return {
        n: digest
        for n, digest in current.items()
        if states.get(n) in store.ACTIVE_STATES
    }


def update_and_record(
    base,
    db_name,
    targets,
    *,
    compose_file=None,
    dry_run=False,
    skip_nested=False,
    per_line=False,
    ctx=None,
):
    """Run ``-u`` for *targets* and refresh stored fingerprints on success.

    A failed update raises ``ClickException`` before fingerprints are
    written, so the next run retries the same modules.
    """
    verb = "Would update" if dry_run else "Updating"
    _report_module_list(verb, targets, per_line=per_line)
    start = time.monotonic()
    returncode = run_update(
        targets,
        db_name,
        compose_file=compose_file,
        dry_run=dry_run,
    )
    elapsed = time.monotonic() - start
    if returncode != 0:
        raise click.ClickException(f"odoo -u failed (exit {returncode}).")
    if dry_run:
        return
    stored = store.read_fingerprints(base, db_name, ctx=ctx) or {}
    stored.update(fingerprint_modules_by_name(base, targets, skip_nested=skip_nested))
    store.write_fingerprints(base, db_name, stored, ctx=ctx)
    echo.success(f"Updated {len(targets)} module(s) in {elapsed:.1f} seconds.")


def install_and_record(
    base, db_name, names, *, compose_file=None, dry_run=False, ctx=None
):
    """Install *names* with ``odoo -i`` and refresh fingerprints on success.

    Modules already installed are reported and skipped. After the run the
    module states are re-checked — an ``-i`` that silently skipped an
    unknown or uninstallable module still reports an error. Fingerprint
    recording mirrors ``update_and_record``: a full baseline when the
    database was not tracked yet, else just the installed modules'.
    """
    states = store.get_module_states(base, db_name, ctx=ctx)
    installed = [
        n for n in names if states is not None and states.get(n) in store.ACTIVE_STATES
    ]
    targets = [n for n in names if n not in installed]
    if installed:
        echo.warning(
            "Already installed — use 'osh apps update' to update: "
            + ", ".join(installed)
        )
    if not targets:
        return

    verb = "Would install" if dry_run else "Installing"
    _report_module_list(verb, targets)
    start = time.monotonic()
    returncode = run_install(
        targets,
        db_name,
        compose_file=compose_file,
        dry_run=dry_run,
    )
    elapsed = time.monotonic() - start
    if returncode != 0:
        raise click.ClickException(f"odoo -i failed (exit {returncode}).")
    if dry_run:
        return

    states = store.get_module_states(base, db_name, ctx=ctx)
    if states is None:
        echo.warning(f"Could not verify the install on '{db_name}'.")
        return
    failed = [n for n in targets if states.get(n) != "installed"]
    if failed:
        raise click.ClickException("Modules were not installed: " + ", ".join(failed))

    stored = store.read_fingerprints(base, db_name, ctx=ctx)
    if stored is None:
        stored = _baseline_mapping(fingerprint_project_modules(base), states)
    else:
        stored.update(fingerprint_modules_by_name(base, targets))
    store.write_fingerprints(base, db_name, stored, ctx=ctx)
    echo.success(f"Installed {len(targets)} module(s) in {elapsed:.1f} seconds.")


def run_update(modules, db_name, *, compose_file=None, dry_run=False):
    """Run ``osh odoo -u <modules>`` and return the process exit code."""
    return _run_module_op(
        "-u", modules, db_name, compose_file=compose_file, dry_run=dry_run
    )


def run_install(modules, db_name, *, compose_file=None, dry_run=False):
    """Run ``osh odoo -i <modules>`` and return the process exit code."""
    return _run_module_op(
        "-i", modules, db_name, compose_file=compose_file, dry_run=dry_run
    )


def _run_module_op(flag, modules, db_name, *, compose_file=None, dry_run=False):
    """Run ``osh odoo <flag> <modules>`` and return the process exit code.

    ``osh odoo`` exec's ``odoo-bin``, so the subprocess return code is Odoo's
    own exit code.
    """
    cmd = [sys.executable, "-m", "osh", "odoo"]
    if compose_file:
        cmd += ["--compose-file", compose_file]
    if dry_run:
        cmd += ["--dry-run"]
    cmd += [
        "-d",
        db_name,
        flag,
        ",".join(modules),
        "--stop-after-init",
        "--no-http",
    ]
    return subprocess.run(cmd).returncode


def _report_module_list(title, names, *, per_line=False):
    """Print a titled module list — comma-separated, or one per line."""
    if not names:
        echo.info(f"{title}: none")
        return
    echo.info(f"{title} ({len(names)}):")
    if per_line:
        for name in names:
            click.echo(f"  {name}")
    else:
        click.echo(",".join(names))
