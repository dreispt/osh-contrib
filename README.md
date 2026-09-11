# osh-contrib

Contrib plugins for [osh](https://github.com/dreispt/osh), the Odoo Shell CLI.
This repository hosts plugins that don't belong in `osh` core — either moved
out of core or contributed by the community.

## Installation

Install the whole collection as a single `osh-contrib` plugin:

```bash
osh plug install https://github.com/dreispt/osh-contrib
```

Then restart `osh` so the new commands are loaded.

## Repository layout

Each `osh_*` directory at the repository root is a plugin package:

```
osh-contrib/
├── __init__.py        # aggregates all osh_* plugins below
└── osh_example/
    └── __init__.py    # exposes get_commands(), COMMANDS, ...
```

The root `__init__.py` imports each plugin package into `SUBPLUGINS` and
re-exports its commands, backends and backup sources. Adding a plugin means
adding a directory **and** registering the import in the root `__init__.py`.

## Adding a plugin

1. Create a package `osh_<name>/` at the repository root.
2. Register it in the root `__init__.py`: add `from . import osh_<name>` and
   append the module to `SUBPLUGINS`.
3. In its `__init__.py`, expose the hooks described in the core
   [plugin guide](https://github.com/dreispt/osh/blob/master/PLUGINS.md):
   - `get_commands()` or `COMMANDS` for Click commands,
   - `get_backends()` or `BACKENDS` for execution backends,
   - `get_backup_sources()` or `BACKUP_SOURCES` for `osh backup` sources.
4. Optionally register it under the `osh.plugins` entry point group in
   `pyproject.toml` so `pip install` also exposes it.

## Development

For local development, symlink the clone into the osh user plugin directory:

```bash
mkdir -p ~/.config/osh/plugins
ln -s /path/to/osh-contrib ~/.config/osh/plugins/osh-contrib
```

Or install it directly from the working copy:

```bash
osh plug install file:///absolute/path/to/osh-contrib
```

Restart `osh` after changing plugin code; plugins are loaded at startup.

Run the tests and linters:

```bash
pip install -e ".[tests]" "osh @ git+https://github.com/dreispt/osh.git"
python -m pytest
pre-commit run --all-files
```

## License

AGPL-3.0-only, same as `osh` core. See `LICENSE`.
