"""Fixtures for the Kiri runtime plugin tests."""

import atexit
import os
import shutil
import sys
import tempfile
from importlib.metadata import entry_points
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FAKEBIN = Path(__file__).resolve().parent / "fakebin"


def _ensure_plugin_dist_info():
    """Make ``osh_runtime_kiri`` discoverable through ``osh.plugins``.

    When the bundle is installed (CI's ``pip install -e .``) the entry
    point already exists under the bundle distribution; in a bare
    checkout a minimal ``.dist-info`` is generated into a temp dir so
    plugin discovery sees the plugin without installing anything. The
    dist-info lives outside the repo — a committed one would duplicate
    the real entry point once the bundle is installed.
    """
    if any(ep.name == "osh_runtime_kiri" for ep in entry_points(group="osh.plugins")):
        return
    dist_dir = Path(tempfile.mkdtemp(prefix="osh-kiri-dist-"))
    atexit.register(shutil.rmtree, dist_dir, ignore_errors=True)
    info = dist_dir / "osh_runtime_kiri-0.1.0.dist-info"
    info.mkdir()
    (info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: osh-runtime-kiri\nVersion: 0.1.0\n",
        encoding="utf-8",
    )
    (info / "entry_points.txt").write_text(
        "[osh.plugins]\nosh_runtime_kiri = osh_runtime_kiri\n",
        encoding="utf-8",
    )
    sys.path.insert(0, str(dist_dir))


# Plugin commands register at ``osh.cli`` import time — the entry point
# must be discoverable and the repo root importable before anything
# imports ``osh.cli``.
_ensure_plugin_dist_info()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture(autouse=True)
def _plugin_registry():
    """Rebuild the plugin registry for each test.

    The registry caches plugin specs discovered from entry points; the
    generated ``.dist-info`` makes ``osh_runtime_kiri`` discoverable, and
    resetting keeps specs from leaking between tests.
    """
    from osh.utils import plugin_loader

    plugin_loader.reset_plugin_registry()
    yield
    plugin_loader.reset_plugin_registry()


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch):
    """Remove ambient variables that would leak into engine scoping.

    A developer's shell may export ``DOCKER_HOST``/``DOCKER_CONTEXT`` or
    ``KIRI_SOCKET``; tests set these values explicitly, so ambient values
    are removed to keep results deterministic.
    """
    for var in (
        "VIRTUAL_ENV",
        "ODOO_RC",
        "OSH_INIT_VERSION",
        "OSH_INIT_EDITION",
        "DOCKER_HOST",
        "DOCKER_CONTEXT",
        "KIRI_SOCKET",
        "OSH_WAIT",
        "OSH_COMPOSE_FILE",
        "COMPOSE_PROJECT_NAME",
        "OSH_REAL_DOCKER",
        "OSH_FAKE_DOCKER",
        "OSH_KIRI_SHARE_TIMEOUT",
    ):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture(autouse=True)
def user_config(tmp_path, monkeypatch):
    """Isolate ``~/.config/osh/config.toml`` per test.

    ``osh init <runtime>`` remembers the runtime as the user's default;
    the write must not touch the developer's actual config.
    """
    path = tmp_path / "home" / ".config" / "osh" / "config.toml"
    monkeypatch.setattr("osh.config.get_user_config_path", lambda: path)
    return path


@pytest.fixture
def tmp_project(tmp_path):
    """Return a temporary project directory with a .osh marker and .git."""
    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)
    (project / ".osh").mkdir(parents=True, exist_ok=True)
    (project / ".git").mkdir(parents=True, exist_ok=True)
    return project


@pytest.fixture
def in_project(monkeypatch, tmp_project):
    """Switch into the temporary project for project-aware commands."""
    monkeypatch.chdir(tmp_project)
    return tmp_project


@pytest.fixture
def fake_docker(tmp_path, monkeypatch):
    """Put the canned-answer ``docker``/``kiri`` on PATH.

    Returns the state dir: response files (``server.json``,
    ``version_rc``, ``docker_ps``, ``kiri_rc`` ...) live there, and every
    fake call is logged to ``calls.log``/``kiri.log``.
    """
    real = shutil.which("docker")
    state = tmp_path / "fake-docker"
    state.mkdir()
    monkeypatch.setenv("OSH_FAKE_DOCKER", str(state))
    monkeypatch.setenv("PATH", f"{FAKEBIN}{os.pathsep}{os.environ['PATH']}")
    if real:
        monkeypatch.setenv("OSH_REAL_DOCKER", real)
    return state


@pytest.fixture
def exec_calls(monkeypatch):
    """Capture ``os.execvp``/``os.execvpe`` calls — ``(exe, args)`` each.

    ``osh exec``/interactive ``osh odoo`` replace the process; capturing
    keeps the test in-process while still exercising the full command
    path up to the exec. Docker runtimes exec through ``execvp``, the
    host runtime through ``execvpe``.
    """
    calls = []
    monkeypatch.setattr(os, "execvp", lambda exe, args: calls.append((exe, args)))
    if hasattr(os, "execvpe"):
        monkeypatch.setattr(
            os,
            "execvpe",
            lambda exe, args, env=None: calls.append((exe, args)),
        )
    return calls


@pytest.fixture
def free_ports(monkeypatch):
    """Pretend every host port is free — no real binds in these tests."""
    monkeypatch.setattr(
        "osh.plugins.osh_runtime_docker.runtimes.port_in_use",
        lambda *a, **kw: False,
    )
