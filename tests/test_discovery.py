"""Tests that core plugin discovery wires up the repo's ``osh_*`` plugins.

Generic over the repo contents: every ``osh_*`` subpackage must load as its
own plugin under the ``osh-contrib`` source, and every capability declared
in its ``OSH_PLUGIN_MANIFEST`` must surface through the loader.
"""

import sys
from pathlib import Path

import click
from osh.utils import plugin_loader

REPO_ROOT = Path(__file__).resolve().parent.parent


def _install_repo(tmp_path, monkeypatch):
    """Symlink this repo into a temporary user plugin directory."""
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    (plugin_dir / "osh-contrib").symlink_to(REPO_ROOT, target_is_directory=True)
    monkeypatch.setattr(plugin_loader, "_user_plugin_dir", lambda: plugin_dir)


def _repo_plugin_packages():
    """Return the ``osh_*`` package names at the repository root."""
    return {
        child.name
        for child in REPO_ROOT.iterdir()
        if child.is_dir()
        and child.name.startswith("osh_")
        and child.name.isidentifier()
        and (child / "__init__.py").is_file()
    }


def _as_list(value):
    return value if isinstance(value, list) else [value]


def _manifest_items(manifest, key):
    """Normalize a manifest entry into a flat list of items."""
    items = manifest.get(key)
    if key in ("hooks", "group_commands"):
        return [x for impl in (items or {}).values() for x in _as_list(impl)]
    return _as_list(items or [])


def _item_key(item):
    """Return a stable identity for a manifest item.

    Loader calls re-import user plugins, so manifest objects cannot be
    compared by identity across ``load_*`` calls — names are stable.
    """
    if isinstance(item, click.Option):
        return ",".join(item.opts + item.secondary_opts)
    return getattr(item, "name", None) or item.__name__


def test_discovery_loads_every_plugin(tmp_path, monkeypatch):
    """Each ``osh_*`` subpackage loads as a plugin under the repo source."""
    _install_repo(tmp_path, monkeypatch)

    loaded = dict(plugin_loader._iter_plugin_modules())
    # Subplugin module names are derived from the repo directory name.
    prefix = "osh_user_plugin_" + plugin_loader._plugin_name_from_path(
        Path("osh-contrib")
    )

    for pkg in _repo_plugin_packages():
        mangled = f"{prefix}_{pkg}"
        assert mangled in sys.modules, f"{pkg} was not imported"
        source = plugin_loader._plugin_source_name(pkg)
        module = loaded.get(source)
        assert module is not None, f"{pkg} has no OSH_PLUGIN_MANIFEST"
        assert module.__name__ == mangled


def test_discovery_surfaces_manifests(tmp_path, monkeypatch):
    """Every manifest capability ends up in the aggregated loader output."""
    _install_repo(tmp_path, monkeypatch)

    loaded = dict(plugin_loader._iter_plugin_modules())
    commands = {(src, c.name) for src, c in plugin_loader.load_plugins()}
    groups = {
        (src, c.name)
        for pairs in plugin_loader.load_group_commands().values()
        for src, c in pairs
    }
    hooks = {
        _item_key(h) for impls in plugin_loader.load_hooks().values() for h in impls
    }
    backends = set(plugin_loader.load_backends())

    for pkg in _repo_plugin_packages():
        source = plugin_loader._plugin_source_name(pkg)
        manifest = loaded[source].OSH_PLUGIN_MANIFEST
        assert manifest, f"{pkg} declares an empty manifest"

        for cmd in _manifest_items(manifest, "commands"):
            assert (source, cmd.name) in commands
        for cmd in _manifest_items(manifest, "group_commands"):
            assert (source, cmd.name) in groups
        for hook in _manifest_items(manifest, "hooks"):
            assert _item_key(hook) in hooks
        for backend in _manifest_items(manifest, "backends"):
            assert backend.name in backends
