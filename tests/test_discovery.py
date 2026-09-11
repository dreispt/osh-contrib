"""Tests that core plugin discovery wires up the repo's ``osh_*`` plugins."""

import sys
from pathlib import Path

from osh.utils import plugin_loader

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_discovery_loads_osh_echohttp(tmp_path, monkeypatch):
    """Installing this repo makes each subpackage load as its own plugin."""
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    (plugin_dir / "osh-contrib").symlink_to(REPO_ROOT, target_is_directory=True)
    monkeypatch.setattr(plugin_loader, "_user_plugin_dir", lambda: plugin_dir)

    commands = {cmd.name: src for src, cmd in plugin_loader.load_plugins()}
    assert commands["_watch-url"] == "osh-echohttp"

    hooks = plugin_loader.load_hooks("odoo.pre_env")
    assert any(hook.__name__ == "pre_env_hook" for hook in hooks)

    options = plugin_loader.load_hooks("odoo.options")
    option_names = {name for opt in options for name in opt.opts + opt.secondary_opts}
    assert "--open" in option_names
    assert "--no-url-watch" in option_names

    # Subplugin modules must be real packages (relative imports work).
    assert "osh_user_plugin_osh_contrib_osh_echohttp" in sys.modules
