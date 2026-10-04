# osh-contrib

Contrib plugins for [osh](https://github.com/dreispt/osh), the Odoo Shell CLI.
This repository hosts plugins that don't belong in `osh` core — either moved
out of core or contributed by the community.

## Installation

Ensure `osh` is installed on your system — the quickest way is `pipx`:

```bash
pipx install git+https://github.com/dreispt/osh.git
```

Plugins are ordinary Python packages installed into `osh`'s environment.
Pick the subsection matching how `osh` was installed — and don't mix the
bundle with individual plugin dists (they ship the same code).

### A single plugin, with pipx

For `osh` installed as a [pipx](https://pipx.pypa.io) app:

```bash
pipx inject osh "osh-dbstats @ git+https://github.com/dreispt/osh-contrib.git#subdirectory=osh_dbstats"
```

Each plugin is its own distribution installed from its repo subdirectory —
swap the name in both places for another plugin.

Remove with `pipx uninject osh osh-dbstats`. No restart is needed —
`osh` discovers entry points on each run.

### All plugins at once, with pipx

The `osh-contrib` bundle distribution ships every plugin in one install:

```bash
pipx inject osh "osh-contrib @ git+https://github.com/dreispt/osh-contrib.git"
```

For a subset, download [`plugins.txt`](plugins.txt) — one spec per
plugin — comment out what you don't want, then feed it to `inject`:

```bash
curl -fsSL -o plugins.txt https://raw.githubusercontent.com/dreispt/osh-contrib/master/plugins.txt
# edit plugins.txt, comment out plugins you don't want
pipx inject osh -r plugins.txt
```

### Without pipx (venv, uv)

Plugins must live in `osh`'s environment, so use that env's installer:

```bash
# venv where `osh` is pip-installed
pip install "osh-dbstats @ git+https://github.com/dreispt/osh-contrib.git#subdirectory=osh_dbstats"

# `osh` installed as a uv tool
uv tool install osh --with "osh-dbstats @ git+https://github.com/dreispt/osh-contrib.git#subdirectory=osh_dbstats"
```

### Legacy: `osh plug install`

The pre-packaging installer still works — it clones the repo into
`~/.config/osh/plugins/`:

```bash
osh plug install https://github.com/dreispt/osh-contrib
```

It is being phased out. Never combine it with a package install of the
same plugin — plugins registered through both paths report
duplicate-registration warnings on every `osh` run
(`osh plug uninstall osh-contrib` removes the legacy one).

## Plugins

Each `osh_*` directory is a self-contained plugin with its own
`osh-plugin.toml` declaration, README and tests:

- [`osh_dbstats`](osh_dbstats/) — database diagnostic dashboard and vacuum
  maintenance (`osh db stats`, `osh db vacuum`).
- [`osh_echohttp`](osh_echohttp/) — prints the browser URL once `osh odoo`
  is ready (`osh odoo --open` also opens it in the browser).
- [`osh_migrations`](osh_migrations/) — collects module `migrations/`
  scripts across OCA version branches (`osh collect-migrations`).
- [`osh_uninstall`](osh_uninstall/) — uninstalls Odoo modules, and their
  installed dependents, from a database (`osh addon uninstall mod_a,mod_b`).
- [`osh_update`](osh_update/) — detects project modules whose code changed
  since the last update and runs `odoo -u` on them (`osh addon update`).

## Repository layout

Similar to an Odoo addons repo, each plugin directory is self-contained —
and each is also an installable distribution (`pipx inject osh
"<name> @ git+…#subdirectory=osh_<name>"`):

```
osh-contrib/
└── osh_example/
    ├── pyproject.toml     # the plugin's distribution (osh.plugins entry point)
    ├── osh-plugin.toml    # declares the plugin's commands and extensions
    ├── __init__.py        # re-exports the plugin's classes
    ├── README.md          # plugin documentation
    ├── ...                # plugin code
    └── tests/             # plugin tests
```

The repository root carries the `osh-contrib` bundle distribution (installs
every plugin at once — used for development and as the install-all spec),
`plugins.txt` (per-plugin spec list), and repo-wide tooling configuration.

## Adding a plugin

1. Create a package `osh_<name>/` at the repository root.
2. Add a `pyproject.toml` for the plugin's distribution — copy an existing
   one and adjust `name`, `version`, `description`, the `osh.plugins` entry
   point, and the `package-dir`/`packages`/`package-data` keys (they all
   reference the package name).
3. Declare the plugin's surface in `osh-plugin.toml`, as described in the
   core [plugin guide](https://github.com/dreispt/osh/blob/master/PLUGINS.md):

   ```toml
   extends = ["db.list"]          # handlers the plugin extends (optional)

   [commands]                     # top-level commands (optional)
   hello = "Say hello."
   ```

   Commands are `CommandHandler` subclasses named by `_cli_name`;
   handler extensions are plain subclasses of the target handler, and
   `Backend`/`BackupSource` subclasses are discovered automatically —
   see the plugin guide.

4. Add a `README.md` documenting the plugin and a `tests/` package with
   its tests.

5. Register it for install-all: append its subdirectory spec to
   `plugins.txt`, and add its `osh.plugins` entry point to the
   `osh-contrib` bundle in the root `pyproject.toml`.

## Development

The root `osh-contrib` package bundles every plugin — install it editable
alongside an editable clone of `osh`, and all plugins load with edits
live on the next `osh` run:

```bash
git clone https://github.com/dreispt/osh
git clone https://github.com/dreispt/osh-contrib
python -m venv .venv && source .venv/bin/activate
pip install -e ./osh -e "./osh-contrib[tests]"
```

For a pipx-managed `osh`, inject a plugin's directory editable instead:
`pipx inject osh -e /path/to/osh-contrib/osh_dbstats`.

Run the tests and linters:

```bash
python -m pytest
pre-commit run --all-files
```

`./run_tests.sh` runs each plugin's test suite in its own pytest process —
plugins are self-contained, so `python -m pytest osh_<name>/` also works on
its own.

## License

LGPL-3.0-only. See `LICENSE`.
