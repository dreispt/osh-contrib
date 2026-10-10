"""Tests that core plugin discovery wires up the repo's ``osh_*`` plugins.

Generic over the repo contents: every ``osh_*`` distribution declaring
``[tool.osh]`` in its ``pyproject.toml`` registers a lazy spec through its
``osh.plugins`` entry point, and every capability declared there surfaces
through the loader — without the plugin module being imported until it is
needed. The loader-level tests require the plugins installed in the test
environment (``pip install -e .`` — the repo's bundle distribution).
"""

import re
import sys
from pathlib import Path

import pytest
from osh.config import tomllib
from osh.handlers import resolve
from osh.utils import plugin_loader
from osh.utils.plugin_registry import plugin_registry

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def registry():
    """The plugin registry, rebuilt from the installed entry points."""
    plugin_loader.reset_plugin_registry()
    yield plugin_registry()
    plugin_loader.reset_plugin_registry()


@pytest.fixture
def installed(registry):
    """Skip unless every repo plugin's entry point is installed here."""
    specs = registry.specs
    missing = [
        pkg
        for pkg in _repo_plugin_packages()
        if pkg not in specs or specs[pkg].kind != "entry_point"
    ]
    if missing:
        pytest.skip(
            f"plugin distributions not installed ({', '.join(missing)}) — "
            "run: pip install -e ."
        )
    return registry


def _repo_plugin_packages():
    """Return ``{name: path}`` for every ``osh_*`` package at the repo root."""
    return {
        child.name: child
        for child in REPO_ROOT.iterdir()
        if child.is_dir()
        and child.name.startswith("osh_")
        and child.name.isidentifier()
        and (child / "__init__.py").is_file()
    }


def _plugin_meta(path):
    """Return the ``[tool.osh]`` declarations of a plugin's pyproject.toml."""
    data = tomllib.loads((path / "pyproject.toml").read_text(encoding="utf-8"))
    return data.get("tool", {}).get("osh") or {}


def _declared_ep(path):
    """Return the ``osh.plugins`` entry points declared by a plugin."""
    data = tomllib.loads((path / "pyproject.toml").read_text(encoding="utf-8"))
    return (data.get("project", {}).get("entry-points") or {}).get("osh.plugins") or {}


def test_every_plugin_package_declares_itself():
    """Every ``osh_*`` package ships pyproject.toml with [tool.osh] + entry point."""
    for pkg, path in _repo_plugin_packages().items():
        assert (path / "pyproject.toml").is_file(), f"{pkg} has no pyproject.toml"
        eps = _declared_ep(path)
        assert eps.get(pkg) == pkg, (
            f"{pkg} does not register '{pkg} = \"{pkg}\"' under "
            '[project.entry-points."osh.plugins"]'
        )
        assert _plugin_meta(path), f"{pkg} declares no [tool.osh] surface"


def test_discovery_registers_lazy_specs(installed):
    """Each package registers a lazy spec — discovery imports nothing."""
    specs = plugin_registry().specs
    for pkg in _repo_plugin_packages():
        spec = specs.get(pkg)
        assert spec is not None, f"{pkg} was not discovered"
        assert spec.lazy
        assert not spec.loaded
        assert pkg not in sys.modules, f"{pkg} was imported at discovery time"


def test_declared_commands_surface(installed):
    """Every declared command gets a lazy stub — still without imports."""
    top = {(src, c.name) for src, c in plugin_loader.load_plugins()}
    groups = {
        (src, group, c.name)
        for group, pairs in plugin_loader.load_group_commands().items()
        for src, c in pairs
    }
    for pkg, path in _repo_plugin_packages().items():
        meta = _plugin_meta(path)
        for name in meta.get("commands") or {}:
            assert (pkg, name) in top
        for group, decls in (meta.get("group_commands") or {}).items():
            for name in decls:
                assert (pkg, group, name) in groups


def test_declared_commands_resolve(installed):
    """Resolving a declared command imports its plugin and finds it."""
    specs = plugin_registry().specs
    for pkg, path in _repo_plugin_packages().items():
        spec = specs[pkg]
        meta = _plugin_meta(path)
        for name in meta.get("commands") or {}:
            command = spec.resolve_command(None, name)
            assert command is not None and command.name == name
        for group, decls in (meta.get("group_commands") or {}).items():
            for name in decls:
                command = spec.resolve_command(group, name)
                assert command is not None and command.name == name


def test_declared_extensions_are_subclasses(installed):
    """Each ``extends`` target gains a subclass when the plugin loads."""
    specs = plugin_registry().specs
    for pkg, path in _repo_plugin_packages().items():
        meta = _plugin_meta(path)
        targets = meta.get("extends") or []
        if not targets:
            continue
        module = specs[pkg].load()
        for target in targets:
            base = resolve(target)
            extensions = [
                impl
                for impl in vars(module).values()
                if isinstance(impl, type)
                and issubclass(impl, base)
                and impl is not base
                and "_cli_name" not in impl.__dict__
            ]
            assert extensions, f"{pkg} extends '{target}' but exposes no subclass"


def _listed_commands(output):
    """Return the command names a group ``--help`` lists in its rows."""
    return {
        match.group(1)
        for line in output.splitlines()
        if (match := re.match(r"^  ([a-z][a-z0-9_-]*)  +\S", line))
    }


def test_apps_group_on_the_cli(installed):
    """``osh apps`` lists the module lifecycle; ``osh db`` hides the old spellings."""
    from click.testing import CliRunner
    from osh.cli import main

    runner = CliRunner()

    result = runner.invoke(main, ["apps", "--help"])
    assert result.exit_code == 0, result.output
    assert {"install", "list", "uninstall", "update"} <= _listed_commands(result.output)

    result = runner.invoke(main, ["db", "--help"])
    assert result.exit_code == 0, result.output
    listed = _listed_commands(result.output)
    assert "update" not in listed
    assert "installed" not in listed
    assert "uninstall" not in listed
