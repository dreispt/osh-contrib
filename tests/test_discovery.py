"""Tests that core plugin discovery wires up the repo's ``osh_*`` plugins.

Generic over the repo contents: every ``osh_*`` subpackage marked with
``osh-plugin.toml`` registers a lazy spec under the ``osh-contrib`` source,
and every capability declared in its metadata surfaces through the loader —
without the plugin module being imported until it is needed.
"""

import sys
from pathlib import Path

import pytest
from osh.handlers import resolve
from osh.utils import plugin_loader
from osh.utils.plugin_registry import plugin_meta, plugin_registry

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def repo_plugins(tmp_path, monkeypatch):
    """Symlink this repo into a temporary user plugin directory."""
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    (plugin_dir / "osh-contrib").symlink_to(REPO_ROOT, target_is_directory=True)
    monkeypatch.setattr("osh.utils.plugin_registry.user_plugin_dir", lambda: plugin_dir)
    plugin_loader.reset_plugin_registry()
    yield plugin_registry()
    plugin_loader.reset_plugin_registry()


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


def test_every_plugin_package_is_marked():
    """Every ``osh_*`` package declares its surface in ``osh-plugin.toml``."""
    for pkg, path in _repo_plugin_packages().items():
        assert (path / "osh-plugin.toml").is_file(), f"{pkg} has no osh-plugin.toml"


def test_discovery_registers_lazy_specs(repo_plugins):
    """Each package registers a lazy spec — discovery imports nothing."""
    specs = plugin_registry().specs
    for pkg in _repo_plugin_packages():
        source = plugin_loader.plugin_source_name(pkg)
        spec = specs.get(source)
        assert spec is not None, f"{pkg} was not discovered"
        assert spec.lazy
        assert not spec.loaded
        mangled = f"osh_user_plugin_osh_contrib_{pkg}"
        assert mangled not in sys.modules, f"{pkg} was imported at discovery time"


def test_declared_commands_surface(repo_plugins):
    """Every declared command gets a lazy stub — still without imports."""
    top = {(src, c.name) for src, c in plugin_loader.load_plugins()}
    groups = {
        (src, group, c.name)
        for group, pairs in plugin_loader.load_group_commands().items()
        for src, c in pairs
    }
    for pkg, path in _repo_plugin_packages().items():
        source = plugin_loader.plugin_source_name(pkg)
        meta = plugin_meta(path)
        for name in meta.get("commands") or {}:
            assert (source, name) in top
        for group, decls in (meta.get("group_commands") or {}).items():
            for name in decls:
                assert (source, group, name) in groups


def test_declared_commands_resolve(repo_plugins):
    """Resolving a declared command imports its plugin and finds it."""
    specs = plugin_registry().specs
    for pkg, path in _repo_plugin_packages().items():
        source = plugin_loader.plugin_source_name(pkg)
        spec = specs[source]
        meta = plugin_meta(path)
        for name in meta.get("commands") or {}:
            command = spec.resolve_command(None, name)
            assert command is not None and command.name == name
        for group, decls in (meta.get("group_commands") or {}).items():
            for name in decls:
                command = spec.resolve_command(group, name)
                assert command is not None and command.name == name


def test_declared_extensions_are_subclasses(repo_plugins):
    """Each ``extends`` target gains a subclass when the plugin loads."""
    specs = plugin_registry().specs
    for pkg, path in _repo_plugin_packages().items():
        meta = plugin_meta(path)
        targets = meta.get("extends") or []
        if not targets:
            continue
        module = specs[plugin_loader.plugin_source_name(pkg)].load()
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
