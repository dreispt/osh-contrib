"""Collection orchestration for ``osh collect-migrations``.

Finds the git repositories below a target directory, resolves each repo's
``N.N`` version branches, checks them out one by one in a temporary
detached ``git worktree``, and copies every ``<module>/migrations``
directory found into the output tree. Kept separate from the Click
command so it can be reused and monkeypatched in tests.
"""

import os
import re
import shutil
import tempfile
from pathlib import Path

import click
from osh import echo
from osh.common import run_subprocess

_VERSION_BRANCH_RE = re.compile(r"^\d+\.\d+$")
_VERSION_ARG_RE = re.compile(r"^\d+(\.\d+)*$")
_MANIFEST_NAMES = ("__manifest__.py", "__openerp__.py")


def collect(
    target,
    output,
    *,
    remote="origin",
    from_version=None,
    to_version=None,
    dry_run=False,
):
    """Collect ``migrations/`` dirs from the repos below *target*.

    *remote* names the remote whose version branches are used;
    *from_version*/*to_version* bound the ``N.N`` branches inspected
    (inclusive); *output* receives a tree mirroring the layout below
    *target* — ``output/<repo>/<module>/migrations/…``.
    """
    target = Path(target).resolve()
    output = Path(output).resolve()
    low = _version_bound(from_version, "--from")
    high = _version_bound(to_version, "--to", fill=float("inf"))
    if low and high and low > high:
        raise click.ClickException(
            f"--from {from_version} is newer than --to {to_version}."
        )

    repos = find_repos(target, exclude=output)
    if not repos:
        echo.info(f"No git repositories found in {target}.")
        return

    total = 0
    scanned = 0
    for repo in repos:
        rel = repo.relative_to(target)
        display = str(rel) if rel.parts else repo.name
        refs = version_refs(repo, remote=remote)
        versions = [v for v in refs if _in_range(v, low, high)]
        if not versions:
            echo.info(f"{display}: no version branches")
            continue
        scanned += 1
        total += _collect_repo(
            repo, display, refs, versions, output / rel, dry_run=dry_run
        )
    if scanned == 0:
        echo.info("No version branches found in any repository.")
        return
    verb = "Would collect" if dry_run else "Collected"
    echo.success(f"{verb} {total} migrations/ dir(s) into {output}.")


def find_repos(target, *, max_depth=4, exclude=None):
    """Return the git repositories at or below *target*.

    Any git checkout counts — a submodule (``.git`` file) as well as a
    plain clone (``.git`` dir). Repositories are not descended into, and
    *exclude*, dot-directories, ``__``-prefixed dirs and ``node_modules``
    are skipped.
    """
    target = Path(target)
    repos = [target] if _is_git_repo(target) else []

    def _walk(current, depth):
        if depth > max_depth:
            return
        try:
            children = sorted(current.iterdir())
        except OSError:
            return
        for child in children:
            if not child.is_dir() or child.is_symlink():
                continue
            if child.name.startswith((".", "__")) or child.name == "node_modules":
                continue
            if exclude is not None and child.resolve() == exclude:
                continue
            if _is_git_repo(child):
                repos.append(child)
            else:
                _walk(child, depth + 1)

    _walk(target, 0)
    return repos


def _is_git_repo(path):
    """Return True when *path* looks like a usable git repository root."""
    git = Path(path) / ".git"
    if git.is_file():
        return True
    return (git / "HEAD").exists()


def version_refs(repo, *, remote="origin"):
    """Return ``{version: refname}`` for *repo*'s ``N.N`` branches.

    *remote*'s tracking branches win over local branches, and local
    branches win over other remotes' tracking ones. The result is sorted
    by version number.
    """
    returncode, stdout, stderr = run_subprocess(
        ["git", "for-each-ref", "--format=%(refname)", "refs/heads", "refs/remotes"],
        cwd=repo,
    )
    if returncode != 0:
        echo.warning(f"Could not list refs in {repo}: {stderr.strip()}")
        return {}
    refs = {}
    for line in stdout.splitlines():
        parsed = _ref_version(line.strip(), remote)
        if parsed is None:
            continue
        version, priority = parsed
        if version not in refs or priority < refs[version][0]:
            refs[version] = (priority, line.strip())
    return {
        version: ref
        for version, (_, ref) in sorted(
            refs.items(), key=lambda item: _version_key(item[0])
        )
    }


def _ref_version(refname, remote):
    """Return ``(version, priority)`` if *refname* is a version branch.

    Lower priority wins: the *remote* tracking branch first, then local
    branches, then other remotes.
    """
    if refname.startswith("refs/heads/"):
        version, priority = refname.removeprefix("refs/heads/"), 1
    elif refname.startswith("refs/remotes/"):
        remote_name, _, version = refname.removeprefix("refs/remotes/").partition("/")
        if not version or version == "HEAD":
            return None
        priority = 0 if remote_name == remote else 2
    else:
        return None
    if not _VERSION_BRANCH_RE.match(version):
        return None
    return version, priority


def _collect_repo(repo, display, refs, versions, repo_out, *, dry_run):
    """Copy the ``migrations/`` dirs of each *version*'s worktree of *repo*."""
    collected = 0
    for version in versions:
        ref = refs[version]
        worktree = Path(tempfile.mkdtemp(prefix=f"osh-migrations-{version}-"))
        try:
            returncode, _, stderr = run_subprocess(
                ["git", "worktree", "add", "--detach", str(worktree), ref],
                cwd=repo,
            )
            if returncode:
                echo.warning(
                    f"{display}: could not check out {version}: {stderr.strip()}"
                )
                continue
            for migrations_dir in _find_migration_dirs(worktree):
                rel = migrations_dir.relative_to(worktree)
                if dry_run:
                    echo.info(f"{display}@{version}: would copy {rel}")
                else:
                    shutil.copytree(migrations_dir, repo_out / rel, dirs_exist_ok=True)
                    echo.info(f"{display}@{version}: {rel}")
                collected += 1
        finally:
            _remove_worktree(repo, worktree)
    return collected


def _remove_worktree(repo, worktree):
    """Remove *worktree* from *repo*, forcing cleanup when needed."""
    run_subprocess(["git", "worktree", "remove", "--force", str(worktree)], cwd=repo)
    if worktree.exists():
        shutil.rmtree(worktree, ignore_errors=True)
        run_subprocess(["git", "worktree", "prune", "--expire=now"], cwd=repo)


def _find_migration_dirs(worktree):
    """Return the ``migrations`` dirs inside *worktree*'s modules.

    A directory counts when it is named ``migrations`` and its parent is an
    Odoo module — i.e. contains a manifest. Symlinked dirs are not
    descended, so the OCA ``setup/<pkg>/odoo/addons`` links never produce
    duplicates.
    """
    found = []
    for root, dirs, _files in os.walk(worktree):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        if "migrations" not in dirs:
            continue
        if any((Path(root) / name).is_file() for name in _MANIFEST_NAMES):
            found.append(Path(root) / "migrations")
            dirs.remove("migrations")
    return found


def _version_key(version):
    """Return a tuple of ints for comparing/sorting version strings."""
    return tuple(int(p) for p in version.split("."))


def _version_bound(value, option, *, fill=0):
    """Parse a ``--from``/``--to`` option value into a 2-part version tuple.

    A shorter bound is padded with *fill* — ``--to 17`` pads with
    ``float("inf")`` so it includes every ``17.x`` branch.
    """
    if value is None:
        return None
    if not _VERSION_ARG_RE.match(value):
        raise click.ClickException(
            f"Invalid {option} version: '{value}' (expected e.g. 17.0)."
        )
    parts = _version_key(value)
    if len(parts) > 2:
        raise click.ClickException(
            f"Invalid {option} version: '{value}' (expected e.g. 17.0)."
        )
    return parts + (fill,) * (2 - len(parts))


def _in_range(version, low, high):
    """Return True when *version* falls inside the [*low*, *high*] bounds."""
    key = _version_key(version)
    return (low is None or key >= low) and (high is None or key <= high)
