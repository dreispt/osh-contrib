"""Aggregate plugin for the osh-contrib repository.

Installed with ``osh plug install https://github.com/dreispt/osh-contrib``,
which clones this repo into ``~/.config/osh/plugins/osh-contrib``. Each
``osh_*`` subpackage is an osh plugin; import it below and add it to
``SUBPLUGINS`` so its commands, backends and backup sources are loaded.
"""

# Contrib plugins are registered here, e.g.:
# from . import osh_example  # noqa: F401

SUBPLUGINS = [
    # osh_example,
]


def _collect(getter, attr):
    items = []
    for mod in SUBPLUGINS:
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
