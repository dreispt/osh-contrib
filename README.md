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

## Plugins

Each `osh_*` directory is a self-contained plugin with its own manifest,
README and tests:

- [`osh_echohttp`](osh_echohttp/) — prints the browser URL once `osh odoo`
  is ready (`osh odoo --open` also opens it in the browser).
- [`osh_uninstall`](osh_uninstall/) — uninstalls Odoo modules, and their
  installed dependents, from a database (`osh addon uninstall mod_a,mod_b`).
- [`osh_update`](osh_update/) — detects project modules whose code changed
  since the last update and runs `odoo -u` on them (`osh addon update`).

## Repository layout

Similar to an Odoo addons repo, the repository root is a bare directory —
each plugin directory is self-contained and `osh` loads every subpackage
declaring `OSH_PLUGIN_MANIFEST` automatically:

```
osh-contrib/
└── osh_example/
    ├── __init__.py        # declares OSH_PLUGIN_MANIFEST = {...}
    ├── README.md          # plugin documentation
    ├── ...                # plugin code
    └── tests/             # plugin tests
```

There is no registration step: adding a plugin is just adding a directory.

## Adding a plugin

1. Create a package `osh_<name>/` at the repository root.
2. In its `__init__.py`, declare `OSH_PLUGIN_MANIFEST` as described in the
   core [plugin guide](https://github.com/dreispt/osh/blob/master/PLUGINS.md):

   ```python
   OSH_PLUGIN_MANIFEST = {
       "commands": [hello],          # click.Command objects
       "backends": [MyBackend],      # Backend subclasses
   }
   ```

   All keys are optional — declare an empty manifest for a plugin that
   only extends operations. Operation extensions are declared on the
   classes themselves via `@extends("op.name")`, and `BackupSource`
   subclasses are discovered automatically — see the plugin guide.

3. Add a `README.md` documenting the plugin and a `tests/` package with
   its tests.

4. Optionally register it under the `osh.plugins` entry point group in
   `pyproject.toml` so `pip install` also exposes it.

## Development

For local development, install the clone in editable mode (symlinked into
the osh user plugin directory):

```bash
osh plug install -e /path/to/osh-contrib
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

`./run_tests.sh` runs each plugin's test suite in its own pytest process —
plugins are self-contained, so `python -m pytest osh_<name>/` also works on
its own.

## License

LGPL-3.0-only. See `LICENSE`.
