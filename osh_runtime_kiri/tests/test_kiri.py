"""Acceptance tests for the ``kiri`` runtime and ``osh odoo --kiri-share``.

Each test reads as a user story: the docstring says what the user wants,
the body sets up a project, runs the real ``osh`` CLI against the canned
``docker``/``kiri`` binaries, and asserts on what the user would see —
files written, URLs printed, engine environment on each subprocess call.
"""

import os
import re
import shutil
import sys
import time
from pathlib import Path

import pytest
from click.testing import CliRunner
from osh.cli import main

FAKEBIN = Path(__file__).resolve().parent / "fakebin"


def _invoke(args, **kwargs):
    """Run the real ``osh`` CLI in-process and return the result."""
    return CliRunner().invoke(main, args, **kwargs)


def _init_kiri(*args):
    """Run ``osh init kiri 19.0`` with the common non-interactive flags."""
    return _invoke(["init", "kiri", "19.0", "--edition", "ce", "--yes", *args])


def _docker_calls(state):
    """Return the logged ``docker`` invocations from the fake's state dir."""
    log = state / "calls.log"
    return log.read_text().splitlines() if log.exists() else []


def _kiri_calls(state):
    """Return the logged ``kiri`` invocations from the fake's state dir."""
    log = state / "kiri.log"
    return log.read_text().splitlines() if log.exists() else []


def _share_calls(state):
    """Return the logged ``kiri share`` argument vectors (argv lines)."""
    return [line for line in _kiri_calls(state) if line.startswith("share ")]


def _kiri_pid(state):
    """Return the fake ``kiri share`` process id, or None when absent."""
    pid_file = state / "kiri.pid"
    return int(pid_file.read_text().strip()) if pid_file.exists() else None


def _wait_process_gone(pid, timeout=5.0):
    """Poll until *pid* no longer exists; fail the test on timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.05)
    raise AssertionError(f"process {pid} still alive {timeout}s after share end")


def _kiri_project(tmp_path, monkeypatch, name="project"):
    """Create an Osh project directory and chdir into it."""
    project = tmp_path / name
    project.mkdir(parents=True, exist_ok=True)
    (project / ".osh").mkdir(exist_ok=True)
    (project / ".git").mkdir(exist_ok=True)
    monkeypatch.chdir(project)
    return project


# A. Engine targeting ----------------------------------------------------


def test_kiri_engine_env_on_every_docker_call(
    in_project, fake_docker, exec_calls, free_ports, monkeypatch
):
    """Every docker call the kiri runtime makes targets Kiri's engine —
    ``DOCKER_HOST`` set to the Kiri socket and ``DOCKER_CONTEXT`` dropped —
    even when the shell exports a different Docker context. Covers init,
    a server run, a non-server exec, a database helper and ``osh stop``."""
    monkeypatch.setenv("DOCKER_CONTEXT", "default")
    monkeypatch.setenv("KIRI_SOCKET", "/tmp/kiri-test.sock")
    monkeypatch.setenv("OSH_WAIT", "1")

    assert _init_kiri().exit_code == 0
    assert _invoke(["odoo"]).exit_code == 0
    assert _invoke(["exec", "ls"]).exit_code == 0
    assert _invoke(["db", "exec", "psql", "-c", "SELECT 1"]).exit_code == 0
    assert _invoke(["stop"]).exit_code == 0

    calls = _docker_calls(fake_docker)
    assert calls, "expected docker invocations to be logged"
    for line in calls:
        assert line.startswith("DOCKER_HOST=unix:///tmp/kiri-test.sock "), line
        assert " DOCKER_CONTEXT=- | " in line, line


def test_kiri_socket_path_becomes_unix_socket(in_project, fake_docker, monkeypatch):
    """``KIRI_SOCKET=/run/kiri/docker.sock`` targets ``unix:///run/kiri/docker.sock``."""
    monkeypatch.setenv("KIRI_SOCKET", "/run/kiri/docker.sock")

    result = _init_kiri("--dry-run")

    assert result.exit_code == 0, result.output
    assert "unix:///run/kiri/docker.sock" in result.output


@pytest.mark.parametrize(
    "value",
    [
        "tcp://kiri.internal:2375",
        "ssh://user@kiri.internal",
        "npipe:////./pipe/kiri",
    ],
)
def test_kiri_socket_with_scheme_is_used_verbatim(
    in_project, fake_docker, monkeypatch, value
):
    """A ``KIRI_SOCKET`` already containing ``://`` is used as-is."""
    monkeypatch.setenv("KIRI_SOCKET", value)

    result = _init_kiri("--dry-run")

    assert result.exit_code == 0, result.output
    assert value in result.output


def _fake_platform(monkeypatch, sys_platform, system):
    """Simulate another OS for engine-default resolution.

    The implementation may key off ``sys.platform`` or
    ``platform.system()`` — patch both so either works.
    """
    import platform

    monkeypatch.setattr(sys, "platform", sys_platform)
    monkeypatch.setattr(platform, "system", lambda: system)


def test_kiri_default_engine_linux(in_project, fake_docker, monkeypatch):
    """On Linux the engine defaults to ``unix:///run/kiri/docker.sock``."""
    _fake_platform(monkeypatch, "linux", "Linux")

    result = _init_kiri("--dry-run")

    assert result.exit_code == 0, result.output
    assert "unix:///run/kiri/docker.sock" in result.output


def test_kiri_default_engine_macos(in_project, fake_docker, monkeypatch, tmp_path):
    """On macOS the engine defaults to ``unix://$HOME/.kiri/run/docker.sock``."""
    home = tmp_path / "home"
    home.mkdir()
    _fake_platform(monkeypatch, "darwin", "Darwin")
    monkeypatch.setenv("HOME", str(home))

    result = _init_kiri("--dry-run")

    assert result.exit_code == 0, result.output
    assert f"unix://{home}/.kiri/run/docker.sock" in result.output


def test_kiri_default_engine_windows(in_project, fake_docker, monkeypatch):
    """On Windows the engine defaults to ``npipe:////./pipe/kiri``."""
    _fake_platform(monkeypatch, "win32", "Windows")

    result = _init_kiri("--dry-run")

    assert result.exit_code == 0, result.output
    assert "npipe:////./pipe/kiri" in result.output


def test_stop_all_scopes_each_runtime_to_its_own_engine(
    tmp_path, fake_docker, monkeypatch
):
    """``osh stop --all`` runs every runtime's teardown against its own
    engine: the docker runtime's container listing keeps the ambient
    Docker environment (no Kiri ``DOCKER_HOST``) while kiri's listing
    targets Kiri's engine. The process environment is untouched after."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DOCKER_CONTEXT", "default")
    monkeypatch.setenv("KIRI_SOCKET", "/tmp/kiri-test.sock")

    result = _invoke(["stop", "--all"])

    assert result.exit_code == 0, result.output
    assert os.environ.get("DOCKER_HOST") is None
    assert os.environ.get("DOCKER_CONTEXT") == "default"

    ps_lines = [line for line in _docker_calls(fake_docker) if " | ps " in line]
    assert any(
        line.startswith("DOCKER_HOST=- ") for line in ps_lines
    ), f"docker runtime's listing missing ambient env: {ps_lines}"
    kiri_lines = [
        line
        for line in ps_lines
        if line.startswith("DOCKER_HOST=unix:///tmp/kiri-test.sock ")
    ]
    assert kiri_lines, f"kiri runtime's listing missing Kiri env: {ps_lines}"
    assert all(" DOCKER_CONTEXT=- | " in line for line in kiri_lines)


def test_init_kiri_unreachable_engine_fails_before_writing(
    in_project, fake_docker, monkeypatch
):
    """When Kiri's engine does not answer, ``osh init kiri`` fails before
    writing anything — the error names the engine address and points at
    Kiri or ``KIRI_SOCKET``."""
    monkeypatch.setenv("KIRI_SOCKET", "/tmp/no-such-kiri.sock")
    (fake_docker / "version_rc").write_text("1")

    result = _init_kiri()

    assert result.exit_code != 0
    output = result.output
    assert "unix:///tmp/no-such-kiri.sock" in output
    assert "KIRI_SOCKET" in output or "Kiri" in output
    assert not (in_project / ".osh" / "docker.toml").exists()


def test_init_kiri_non_kiri_engine_warns_but_continues(in_project, fake_docker):
    """A reachable engine that is not Kiri produces a warning, and init
    still completes — the user may point KIRI_SOCKET at plain Docker."""
    (fake_docker / "server.json").write_text(
        '{"Components":[{"Name":"Docker","Version":"27.0.0"}]}'
    )

    result = _init_kiri()

    assert result.exit_code == 0, result.output
    assert re.search(r"not (a )?Kiri|no Kiri|isn't Kiri", result.output, re.I)
    assert (in_project / ".osh" / "docker.toml").exists()


def test_init_kiri_dry_run_reports_engine_without_probing(
    in_project, fake_docker, monkeypatch
):
    """``osh init kiri --dry-run`` reports the engine address it would
    use and never probes it — a failing engine must not matter."""
    monkeypatch.setenv("KIRI_SOCKET", "/tmp/kiri-test.sock")
    (fake_docker / "version_rc").write_text("1")

    result = _init_kiri("--dry-run")

    assert result.exit_code == 0, result.output
    assert "unix:///tmp/kiri-test.sock" in result.output
    assert not any("version --format" in line for line in _docker_calls(fake_docker))


def test_init_kiri_reports_kiri_engine(in_project, fake_docker, monkeypatch):
    """``osh init kiri`` reports the engine as ``Kiri <version> at
    <address>`` — the init-phase diagnostics print it as a note."""
    monkeypatch.setenv("KIRI_SOCKET", "/tmp/kiri-test.sock")

    result = _init_kiri()

    assert result.exit_code == 0, result.output
    assert "Kiri 0.2.1 at unix:///tmp/kiri-test.sock" in result.output


# B. Names -----------------------------------------------------------------


def test_compose_override_labels_odoo_port_and_domain(
    in_project, fake_docker, free_ports, monkeypatch
):
    """The generated Compose override labels the Odoo service with the
    Kiri HTTP port (8069 by default) and the project domain."""
    monkeypatch.setenv("OSH_WAIT", "1")
    assert _init_kiri("--domain", "my-shop").exit_code == 0

    assert _invoke(["odoo"]).exit_code == 0

    override = in_project / ".osh" / "docker-compose.osh.yml"
    assert override.is_file(), "expected the generated Compose override"
    text = override.read_text()
    assert "dev.kiri.http.port" in text
    assert "8069" in text
    assert "dev.kiri.domain" in text
    assert "my-shop" in text


def test_compose_override_uses_requested_odoo_port(
    in_project, fake_docker, free_ports, monkeypatch
):
    """``osh odoo -p <n>`` republishes the port, and the Kiri label
    follows the requested port instead of 8069."""
    monkeypatch.setenv("OSH_WAIT", "1")
    assert _init_kiri("--domain", "my-shop").exit_code == 0

    assert _invoke(["odoo", "-p", "19069"]).exit_code == 0

    override = in_project / ".osh" / "docker-compose.osh.yml"
    assert override.is_file(), "expected the generated Compose override"
    text = override.read_text()
    assert "dev.kiri.http.port" in text
    assert "19069" in text


def test_domain_derived_from_directory_name(
    tmp_path, fake_docker, free_ports, monkeypatch
):
    """A project checked out as ``My_Project`` gets the Kiri domain
    ``my-project`` — lowercased, unsafe characters collapsed to ``-``."""
    project = _kiri_project(tmp_path, monkeypatch, name="My_Project")
    monkeypatch.setenv("OSH_WAIT", "1")

    assert _init_kiri().exit_code == 0
    assert _invoke(["odoo"]).exit_code == 0

    override = project / ".osh" / "docker-compose.osh.yml"
    assert override.is_file(), "expected the generated Compose override"
    text = override.read_text()
    assert "dev.kiri.domain" in text
    assert "my-project" in text


def test_domain_option_is_stored_and_kept_on_reinit(in_project, fake_docker):
    """``osh init kiri --domain NAME`` stores ``kiri_domain`` in
    ``.osh/docker.toml``; re-running init without the flag keeps it."""
    assert _init_kiri("--domain", "shop.example.com").exit_code == 0

    toml_text = (in_project / ".osh" / "docker.toml").read_text()
    assert "kiri_domain" in toml_text
    assert "shop.example.com" in toml_text

    assert _init_kiri().exit_code == 0
    toml_text = (in_project / ".osh" / "docker.toml").read_text()
    assert "shop.example.com" in toml_text


def test_invalid_domain_is_a_usage_error_writing_nothing(in_project, fake_docker):
    """``--domain`` must be a valid Kiri domain; anything else is a usage
    error and no ``.osh/docker.toml`` is written."""
    result = _init_kiri("--domain", "Bad_Domain!")

    assert result.exit_code == 2
    assert not (in_project / ".osh" / "docker.toml").exists()


def test_odoo_server_run_prints_kiri_url(
    in_project, fake_docker, free_ports, monkeypatch
):
    """``osh odoo`` prints ``Odoo: http://<domain>.kiri.localhost`` to
    stderr so the user knows where Kiri serves the project."""
    monkeypatch.setenv("OSH_WAIT", "1")
    assert _init_kiri("--domain", "my-shop").exit_code == 0

    result = _invoke(["odoo"])

    assert result.exit_code == 0, result.output
    assert "Odoo: http://my-shop.kiri.localhost" in result.stderr


def test_odoo_exec_with_only_flags_prints_kiri_url(
    in_project, fake_docker, free_ports, monkeypatch, exec_calls
):
    """``osh exec odoo --dev=all -d mydb`` is still a server run — no
    subcommand, only options — so it prints the Kiri URL like ``osh odoo``."""
    monkeypatch.setenv("OSH_WAIT", "1")
    assert _init_kiri("--domain", "my-shop").exit_code == 0

    result = _invoke(["exec", "odoo", "--dev=all", "-d", "mydb"])

    assert result.exit_code == 0, result.output
    assert "Odoo: http://my-shop.kiri.localhost" in result.stderr


def test_non_server_commands_do_not_print_kiri_url(in_project, fake_docker, exec_calls):
    """``osh exec`` (a shell), ``osh exec ls`` and ``osh exec odoo shell``
    are not server runs —
    they must not print the Odoo URL (only ``osh odoo`` and flag-only
    ``odoo`` invocations do)."""
    assert _init_kiri("--domain", "my-shop").exit_code == 0

    for args in (["exec"], ["exec", "ls"], ["exec", "odoo", "shell"]):
        result = _invoke(args)
        assert result.exit_code == 0, result.output
        assert "kiri.localhost" not in result.output
        assert "kiri.localhost" not in (result.stderr or "")


def test_init_kiri_prints_project_url(in_project, fake_docker):
    """A successful ``osh init kiri`` ends by printing the project's
    ``http://<domain>.kiri.localhost`` URL."""
    result = _init_kiri("--domain", "my-shop")

    assert result.exit_code == 0, result.output
    assert "http://my-shop.kiri.localhost" in result.output


# C. Sharing — ``osh odoo --kiri-share`` --------------------------------------


def test_kiri_share_makes_odoo_public_for_the_run(
    in_project, fake_docker, free_ports, monkeypatch
):
    """``osh odoo --kiri-share`` starts ``kiri share <port> --json``
    before Odoo, prints the public ``*.runkiri.cloud`` URL, and the
    share ends when the Odoo run ends — the fake kiri logs ``stopped``
    once its lifeline closes."""
    monkeypatch.setenv("OSH_WAIT", "1")
    assert _init_kiri().exit_code == 0

    result = _invoke(["odoo", "--kiri-share"])

    assert result.exit_code == 0, result.output
    assert "Odoo (public): https://demo-4k2x.runkiri.cloud" in result.stderr
    assert _share_calls(fake_docker) == ["share 8069 --json"]
    pid = _kiri_pid(fake_docker)
    assert pid, "the fake kiri did not record its pid"
    _wait_process_gone(pid)
    assert _kiri_calls(fake_docker)[-1] == "stopped"


def test_kiri_share_on_exec_path_starts_share_and_prints_url(
    in_project, fake_docker, exec_calls, free_ports
):
    """Without ``OSH_WAIT`` the share still starts and the URL prints
    before ``osh`` execs Odoo — the captured exec proves the run got
    that far, and closing the lifeline on return ends the share."""
    assert _init_kiri().exit_code == 0

    result = _invoke(["odoo", "--kiri-share"])

    assert result.exit_code == 0, result.output
    assert "Odoo (public): https://demo-4k2x.runkiri.cloud" in result.stderr
    assert _share_calls(fake_docker) == ["share 8069 --json"]
    assert exec_calls, "expected the run to reach os.execvp"


def test_kiri_share_name_and_port_options(
    in_project, fake_docker, exec_calls, free_ports
):
    """``--kiri-share-name NAME`` reserves ``NAME.runkiri.cloud`` and
    implies ``--kiri-share``; ``-p``/``--http-port`` set the shared port."""
    assert _init_kiri().exit_code == 0

    result = _invoke(["odoo", "--kiri-share-name", "demo"])
    assert result.exit_code == 0, result.output
    tokens = _share_calls(fake_docker)[0].split()
    assert "--name" in tokens
    assert "demo" in tokens

    result = _invoke(["odoo", "-p", "19069", "--kiri-share"])
    assert result.exit_code == 0, result.output
    assert _share_calls(fake_docker)[1] == "share 19069 --json"

    result = _invoke(["odoo", "--http-port=19069", "--kiri-share"])
    assert result.exit_code == 0, result.output
    assert _share_calls(fake_docker)[2] == "share 19069 --json"


def test_kiri_share_works_for_docker_runtime_project(
    in_project, fake_docker, exec_calls, monkeypatch
):
    """Share is not Kiri-specific: a plain ``docker`` runtime project
    shares its Odoo port the same way — Kiri Share tunnels a local port."""
    assert (
        _invoke(["init", "docker", "19.0", "--edition", "ce", "--yes"]).exit_code == 0
    )

    result = _invoke(["odoo", "--kiri-share"])

    assert result.exit_code == 0, result.output
    assert "Odoo (public): https://demo-4k2x.runkiri.cloud" in result.stderr
    assert _share_calls(fake_docker) == ["share 8069 --json"]


def test_kiri_share_works_for_host_runtime_project(
    in_project, fake_docker, exec_calls, monkeypatch
):
    """Even a host-runtime project — no container stack at all — can
    share the port its Odoo config reports."""
    monkeypatch.setattr("osh.commands.odoo_cmd._port_in_use", lambda *a, **kw: False)

    result = _invoke(["odoo", "--kiri-share"])

    assert result.exit_code == 0, result.output
    assert "Odoo (public): https://demo-4k2x.runkiri.cloud" in result.stderr
    assert _share_calls(fake_docker) == ["share 8069 --json"]


def test_kiri_share_dry_run_prints_command_and_starts_nothing(
    in_project, fake_docker, monkeypatch
):
    """``osh odoo --dry-run --kiri-share`` prints
    ``Would share: kiri share 8069 --json`` and starts nothing."""
    assert _init_kiri().exit_code == 0

    result = _invoke(["odoo", "--dry-run", "--kiri-share"])

    assert result.exit_code == 0, result.output
    assert "Would share: kiri share 8069 --json" in result.output
    assert not (fake_docker / "kiri.log").exists()


def test_kiri_share_without_kiri_binary_fails_before_odoo(
    in_project, fake_docker, exec_calls, monkeypatch, tmp_path
):
    """Without ``kiri`` on ``PATH``, ``osh odoo --kiri-share`` fails
    before Odoo starts, pointing at the Kiri download page."""
    assert _init_kiri().exit_code == 0

    bin_dir = tmp_path / "bin-no-kiri"
    bin_dir.mkdir()
    os.symlink(FAKEBIN / "docker", bin_dir / "docker")
    path = os.environ["PATH"].replace(f"{FAKEBIN}{os.pathsep}", "")
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{path}")
    if shutil.which("kiri"):
        pytest.skip("a real kiri binary is on PATH")

    result = _invoke(["odoo", "--kiri-share"])

    assert result.exit_code != 0
    assert "https://runkiri.com/download" in result.output
    assert not exec_calls
    assert not _share_calls(fake_docker)


def test_kiri_share_failure_fails_before_odoo(in_project, fake_docker, exec_calls):
    """When ``kiri share`` ends before going live — here "not signed
    in" — ``osh odoo`` fails before Odoo starts, shows Kiri's message
    and the ``kiri share login`` hint, and leaves no kiri process."""
    assert _init_kiri().exit_code == 0
    (fake_docker / "kiri_fail").write_text("not signed in")

    result = _invoke(["odoo", "--kiri-share"])

    assert result.exit_code != 0
    assert "not signed in" in result.output
    assert "kiri share login" in result.output
    assert not exec_calls
    pid = _kiri_pid(fake_docker)
    assert pid, "the fake kiri did not record its pid"
    _wait_process_gone(pid)


def test_kiri_share_ignored_for_non_http_runs(in_project, fake_docker, exec_calls):
    """Runs that serve no HTTP — an Odoo subcommand or
    ``--stop-after-init`` — warn that ``--kiri-share`` is ignored and
    start no share; the run itself proceeds."""
    assert _init_kiri().exit_code == 0

    for args in (
        ["odoo", "shell", "--kiri-share"],
        ["odoo", "--kiri-share", "--stop-after-init"],
    ):
        result = _invoke(args)
        assert result.exit_code == 0, result.output
        # The tmp project path embeds this test's name — a bare
        # "ignored" substring would match it vacuously.
        assert "--kiri-share is ignored" in result.output
    assert not (fake_docker / "kiri.log").exists()


def test_kiri_share_timeout_fails_and_cleans_up(
    in_project, fake_docker, exec_calls, monkeypatch
):
    """A share that never goes live fails once ``OSH_KIRI_SHARE_TIMEOUT``
    seconds pass, and the hung kiri process is cleaned up."""
    monkeypatch.setenv("OSH_KIRI_SHARE_TIMEOUT", "1")
    assert _init_kiri().exit_code == 0
    (fake_docker / "kiri_hang").write_text("1")

    result = _invoke(["odoo", "--kiri-share"])

    assert result.exit_code != 0
    assert "timed out" in result.output
    assert not exec_calls
    pid = _kiri_pid(fake_docker)
    assert pid, "the fake kiri did not record its pid"
    _wait_process_gone(pid)


# D. Packaging -------------------------------------------------------------


def test_kiri_runtime_and_share_option_are_discovered():
    """The plugin's ``[tool.osh]`` declarations register the ``kiri``
    runtime for ``osh init kiri`` and extend ``osh odoo`` with
    ``--kiri-share`` — resolved lazily through the normal plugin
    machinery. The old ``osh kiri share`` command group is gone."""
    from osh.utils import plugin_loader

    from osh_runtime_kiri.runtimes import KiriRuntime

    plugin_loader.reset_plugin_registry()
    spec = plugin_loader.plugin_registry().specs.get("osh_runtime_kiri")
    assert spec is not None
    assert spec.lazy

    runtime_cls = plugin_loader.get_runtime_class("kiri")
    assert runtime_cls is KiriRuntime

    result = _invoke(["odoo", "--help"])
    assert result.exit_code == 0, result.output
    assert "--kiri-share" in result.output
    # Help text wraps at the terminal width — compare unwrapped.
    assert "publicly available on the Internet" in " ".join(result.output.split())

    result = _invoke(["kiri", "share", "--help"])
    assert result.exit_code != 0

    result = _invoke(["init", "kiri", "--help"])
    assert result.exit_code == 0, result.output
    assert "--domain" in result.output
