"""Tests for the ``osh collect-migrations`` command."""

import subprocess

from click.testing import CliRunner

from osh_migrations.commands import collect_migrations

from .conftest import _git, requires_git


def run_collect(*args):
    """Invoke ``collect-migrations`` with *args* in the current directory."""
    return CliRunner().invoke(collect_migrations, [str(a) for a in args])


def _git_out(cwd, *args):
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def _clone(src, dst):
    _git_out(src.parent, "clone", str(src), str(dst))
    return dst


@requires_git
def test_collects_migrations_across_branches(copy_repo, in_tmp):
    """Each branch's migrations/ dirs merge into one module tree."""
    copy_repo(in_tmp / "external" / "OCA" / "server-tools")

    result = run_collect("external")

    assert result.exit_code == 0
    base = in_tmp / "migration" / "OCA" / "server-tools" / "mod_a" / "migrations"
    assert (base / "17.0.1.0" / "pre-migration.py").is_file()
    assert (base / "18.0.1.0" / "pre-migration.py").is_file()
    assert (base / "19.0.1.0" / "post-migration.py").is_file()
    assert "Collected 3 migrations/ dir(s)" in result.output


@requires_git
def test_clone_checkout_is_untouched(copy_repo, in_tmp):
    """The scanned repo keeps its branch and dirty working tree."""
    repo = copy_repo(in_tmp / "external" / "repo")
    (repo / "dirty.txt").write_text("x")
    before = _git_out(repo, "branch", "--show-current")

    result = run_collect("external")

    assert result.exit_code == 0
    assert _git_out(repo, "branch", "--show-current") == before
    assert (repo / "dirty.txt").is_file()
    assert len(_git_out(repo, "worktree", "list").splitlines()) == 1


@requires_git
def test_from_to_bounds_versions(repo, in_tmp):
    """--from/--to limit which version branches are collected."""
    result = run_collect("repo", "--from", "18.0", "--to", "19.0")

    assert result.exit_code == 0
    base = in_tmp / "migration" / "mod_a" / "migrations"
    assert not (base / "17.0.1.0").exists()
    assert (base / "18.0.1.0" / "pre-migration.py").is_file()
    assert (base / "19.0.1.0" / "post-migration.py").is_file()


@requires_git
def test_dry_run_copies_nothing(repo, in_tmp):
    result = run_collect("repo", "--dry-run")

    assert result.exit_code == 0
    assert "would copy" in result.output
    assert not (in_tmp / "migration").exists()


@requires_git
def test_ignores_migrations_without_manifest(make_repo, in_tmp):
    """A ``migrations`` dir outside a module is not collected."""
    repo = make_repo(in_tmp / "repo", {"18.0": {"mod_a": ["18.0.1.0/pre.py"]}})
    _git(repo, "checkout", "18.0")
    stray = repo / "docs" / "migrations" / "18.0.1.0"
    stray.mkdir(parents=True)
    (stray / "not-a-script.py").write_text("x")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "stray")

    result = run_collect("repo")

    assert result.exit_code == 0
    assert (in_tmp / "migration" / "mod_a" / "migrations").is_dir()
    assert not (in_tmp / "migration" / "docs").exists()


@requires_git
def test_remote_branches_are_collected(repo, in_tmp):
    """Repos with only remote-tracking version branches still work."""
    _clone(repo, in_tmp / "clone")

    result = run_collect("clone")

    assert result.exit_code == 0
    base = in_tmp / "migration" / "mod_a" / "migrations"
    assert (base / "17.0.1.0" / "pre-migration.py").is_file()
    assert (base / "19.0.1.0" / "post-migration.py").is_file()


@requires_git
def test_remote_option_selects_remote(make_repo, in_tmp):
    """--remote collects the named remote's branches over origin's."""
    origin = make_repo(in_tmp / "origin-src", {"18.0": {"mod_a": ["18.0.1.0/o.py"]}})
    upstream = make_repo(in_tmp / "up-src", {"18.0": {"mod_a": ["18.0.1.0/u.py"]}})
    clone = _clone(origin, in_tmp / "clone")
    _git(clone, "remote", "add", "upstream", str(upstream))
    _git(clone, "fetch", "upstream")

    result = run_collect("clone", "--remote", "upstream")

    assert result.exit_code == 0
    base = in_tmp / "migration" / "mod_a" / "migrations" / "18.0.1.0"
    assert (base / "u.py").is_file()
    assert not (base / "o.py").exists()


@requires_git
def test_target_repo_collects_to_output_root(repo, in_tmp):
    """When TARGET itself is the repo, modules land at the output root."""
    result = run_collect("repo", "-o", "collected")

    assert result.exit_code == 0
    base = in_tmp / "collected" / "mod_a" / "migrations"
    assert (base / "17.0.1.0" / "pre-migration.py").is_file()


def test_no_repos(in_tmp):
    (in_tmp / "empty").mkdir()

    result = run_collect("empty")

    assert result.exit_code == 0
    assert "No git repositories found" in result.output


@requires_git
def test_repo_without_version_branches(make_repo, in_tmp):
    make_repo(in_tmp / "repo", {})

    result = run_collect("repo")

    assert result.exit_code == 0
    assert "no version branches" in result.output
    assert not (in_tmp / "migration").exists()


def test_invalid_version_bound(tmp_path):
    result = run_collect(tmp_path, "--from", "seventeen")
    assert result.exit_code != 0
    assert "Invalid --from version" in result.output

    result = run_collect(tmp_path, "--to", "17.0.1")
    assert result.exit_code != 0
    assert "Invalid --to version" in result.output


def test_from_newer_than_to(tmp_path):
    result = run_collect(tmp_path, "--from", "19.0", "--to", "17.0")
    assert result.exit_code != 0
    assert "newer than --to" in result.output
