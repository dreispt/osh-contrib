"""Aggregate plugin for the osh-contrib repository.

Installed with ``osh plug install https://github.com/dreispt/osh-contrib``,
which clones this repo into ``~/.config/osh/plugins/osh-contrib``. Each
``osh_*`` subpackage is an osh plugin; this module merges their
``OSH_PLUGIN_MANIFEST`` dicts so they all load at once.
"""

import pkgutil
from importlib import import_module

from osh import echo

_PLUGIN_PREFIX = "osh_"
_MANIFEST_KEYS = ("commands", "backends", "backup_sources")


def _iter_subplugins():
    path = globals().get("__path__")
    if not path:
        # Not loaded as a package (e.g. imported as a plain module); there is
        # no package context to resolve ``osh_*`` subplugins against.
        return
    for info in pkgutil.iter_modules(path):
        if not info.ispkg or not info.name.startswith(_PLUGIN_PREFIX):
            continue
        try:
            yield import_module(f".{info.name}", __name__)
        except Exception as exc:
            echo.warning(
                f"Could not load contrib plugin '{info.name}': {exc}", err=True
            )


def _build_manifest():
    manifest = {key: [] for key in _MANIFEST_KEYS}
    for mod in _iter_subplugins():
        sub = getattr(mod, "OSH_PLUGIN_MANIFEST", {})
        for key in _MANIFEST_KEYS:
            manifest[key].extend(sub.get(key, []))
    return manifest


OSH_PLUGIN_MANIFEST = _build_manifest()
