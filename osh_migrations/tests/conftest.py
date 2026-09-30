"""Fixtures for the ``osh_migrations`` test suite."""

import shutil
import subprocess

import pytest

requires_git = pytest.mark.skipif(
    shutil.which("git") is None, reason="git not available"
)

#: Standard version branches used by most tests.
BRANCHES = {
    "17.0": {"mod_a": ["17.0.1.0/pre-migration.py"]},
    "18.0": {"mod_a": ["18.0.1.0/pre-migration.py"]},
    "19.0": {"mod_a": ["19.0.1.0/post-migration.py"]},
}


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _git_commit(repo, message):
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message)


def _build_repo(path, branches):
    """Create a git repo at *path* with one branch per version.

    ``branches`` maps a version (``"17.0"``) to ``{module: [scripts]}``
    where each script is a path below ``<module>/migrations/``. Each
    branch is cut from the initial commit, so a branch's tree only
    contains its own modules. The repo is left on its initial branch.
    """
    path.mkdir(parents=True)
    _git(path, "init")
    _git(path, "config", "user.email", "x@y")
    _git(path, "config", "user.name", "x")
    (path / "README").write_text("x")
    _git_commit(path, "init")
    base = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    for version, modules in branches.items():
        _git(path, "checkout", "-b", version, base)
        for module, scripts in modules.items():
            (path / module).mkdir(parents=True, exist_ok=True)
            (path / module / "__manifest__.py").write_text("{}")
            for script in scripts:
                script_file = path / module / "migrations" / script
                script_file.parent.mkdir(parents=True, exist_ok=True)
                script_file.write_text(f"# {version} {module} {script}\n")
        _git_commit(path, version)
    _git(path, "checkout", base)
    return path


@pytest.fixture
def in_tmp(tmp_path, monkeypatch):
    """Run the test from *tmp_path* — the ``migration/`` output lands here."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def make_repo():
    """Return a factory creating a git repo with custom version branches."""
    return _build_repo


@pytest.fixture(scope="session")
def _versioned_repo(tmp_path_factory):
    """The standard BRANCHES repo, built once and shared by all tests."""
    return _build_repo(tmp_path_factory.mktemp("base") / "repo", BRANCHES)


@pytest.fixture
def copy_repo(_versioned_repo):
    """Return a factory copying the shared versioned repo to *path*."""

    def _copy(path):
        shutil.copytree(_versioned_repo, path)
        return path

    return _copy


@pytest.fixture
def repo(copy_repo, in_tmp):
    """A copy of the shared versioned repo at ``in_tmp/repo``."""
    return copy_repo(in_tmp / "repo")
