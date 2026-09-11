"""Aggregate plugin for the osh-contrib repository.

Installed with ``osh plug install https://github.com/dreispt/osh-contrib``,
which clones this repo into ``~/.config/osh/plugins/osh-contrib``. Each
``osh_*`` subpackage is an osh plugin; this module re-exports their
commands, backends and backup sources so they all load at once.
"""

import pkgutil
from importlib import import_module

from osh import echo

_PLUGIN_PREFIX = "osh_"


def _iter_subplugins():
    for info in pkgutil.iter_modules(__path__):
        if not info.ispkg or not info.name.startswith(_PLUGIN_PREFIX):
            continue
        try:
            yield import_module(f".{info.name}", __name__)
        except Exception as exc:
            echo.warning(
                f"Could not load contrib plugin '{info.name}': {exc}", err=True
            )


def _collect(getter, attr):
    items = []
    for mod in _iter_subplugins():
        if hasattr(mod, getter):
            items.extend(getattr(mod, getter)())
        else:
            items.extend(getattr(mod, attr, []))
    return items


def get_commands():
    return _collect("get_commands", "COMMANDS")


def get_backends():
    return _collect("get_backends", "BACKENDS")


def get_backup_sources():
    return _collect("get_backup_sources", "BACKUP_SOURCES")
