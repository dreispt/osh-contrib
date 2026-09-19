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

Each `osh_*` directory is a self-contained plugin with its own
`osh-plugin.toml` declaration, README and tests:

- [`osh_echohttp`](osh_echohttp/) — prints the browser URL once `osh odoo`
  is ready (`osh odoo --open` also opens it in the browser).
- [`osh_uninstall`](osh_uninstall/) — uninstalls Odoo modules, and their
  installed dependents, from a database (`osh addon uninstall mod_a,mod_b`).
- [`osh_update`](osh_update/) — detects project modules whose code changed
  since the last update and runs `odoo -u` on them (`osh addon update`).

## Repository layout

Similar to an Odoo addons repo, the repository root is a bare directory —
each plugin directory is self-contained and `osh` discovers every subpackage
marked with an `osh-plugin.toml` file automatically:

```
osh-contrib/
└── osh_example/
    ├── osh-plugin.toml    # declares the plugin's commands and extensions
    ├── __init__.py        # re-exports the plugin's classes
    ├── README.md          # plugin documentation
    ├── ...                # plugin code
    └── tests/             # plugin tests
```

There is no registration step: adding a plugin is just adding a directory.

## Adding a plugin

1. Create a package `osh_<name>/` at the repository root.
2. Declare the plugin's surface in `osh-plugin.toml`, as described in the
   core [plugin guide](https://github.com/dreispt/osh/blob/master/PLUGINS.md):

   ```toml
   description = "What the plugin does."
   extends = ["db.list"]          # handlers the plugin extends (optional)

   [commands]                     # top-level commands (optional)
   hello = "Say hello."
   ```

   Commands are `CommandHandler` subclasses named by `_cli_name`;
   handler extensions are plain subclasses of the target handler, and
   `Backend`/`BackupSource` subclasses are discovered automatically —
   see the plugin guide.

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
