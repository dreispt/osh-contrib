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
       "backup_sources": [MySource], # BackupSource subclasses
       "hooks": {"odoo.pre_env": []},# hook point implementations
   }
   ```

   All keys are optional.

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

## License

LGPL-3.0-only. See `LICENSE`.
