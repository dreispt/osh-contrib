"""Tests for the osh-contrib root aggregator plugin."""

import importlib.util
import sys
import types
from pathlib import Path

import click


def _load_root_plugin():
    init_file = Path(__file__).parent.parent / "__init__.py"
    spec = importlib.util.spec_from_file_location("osh_contrib_test", init_file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_aggregator_exposes_plugin_hooks():
    module = _load_root_plugin()
    assert isinstance(module.get_commands(), list)
    assert isinstance(module.get_backends(), list)
    assert isinstance(module.get_backup_sources(), list)


def test_aggregator_collects_from_subplugins(monkeypatch):
    fake = types.ModuleType("osh_fake")
    cmd = click.Command("fake")
    fake.COMMANDS = [cmd]
    module = _load_root_plugin()
    monkeypatch.setattr(module, "SUBPLUGINS", [fake])
    assert module.get_commands() == [cmd]
