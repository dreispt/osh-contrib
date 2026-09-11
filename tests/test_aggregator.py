"""Tests for the osh-contrib root aggregator plugin."""

import importlib.util
import sys
from pathlib import Path


def _load_root_plugin():
    init_file = Path(__file__).parent.parent / "__init__.py"
    spec = importlib.util.spec_from_file_location("osh_contrib_test", init_file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_aggregator_exposes_manifest():
    module = _load_root_plugin()
    assert module.OSH_PLUGIN_MANIFEST == {
        "commands": [],
        "backends": [],
        "backup_sources": [],
    }


def test_aggregator_discovers_osh_subplugins(tmp_path, monkeypatch):
    sub = tmp_path / "osh_fake"
    sub.mkdir()
    (sub / "__init__.py").write_text(
        "import click\n"
        "\n"
        "@click.command(name='fake')\n"
        "def fake():\n"
        "    pass\n"
        "\n"
        "OSH_PLUGIN_MANIFEST = {'commands': [fake]}\n"
    )
    module = _load_root_plugin()
    monkeypatch.setattr(module, "__path__", [str(tmp_path)])
    manifest = module._build_manifest()
    assert [cmd.name for cmd in manifest["commands"]] == ["fake"]
