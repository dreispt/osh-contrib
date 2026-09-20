# osh_echohttp

Prints the browser URL once `osh odoo` is actually ready to serve requests:

```bash
osh odoo           # prints "🚀 Odoo ready: http://mydb.localhost:8069" when up
osh odoo --open    # also opens the URL in your browser
```

Since `osh odoo` replaces itself with the Odoo process (`exec`), the plugin
spawns a detached `osh echohttp` sidecar that TCP-polls the HTTP port
and writes to the same terminal — the line interleaves with Odoo's own log
output, so it is printed with an emoji and surrounding blank lines to stand
out. The port is resolved from `-p`/`--http-port`/`--xmlrpc-port` arguments,
then the effective Odoo config, defaulting to 8069; the database name becomes
a `localhost` subdomain (`mydb.localhost`, handy with a `%d` dbfilter). The
watcher exits silently after a 2-minute timeout so it never lingers on
failed boots.

- `--no-url-watch` or `OSH_URL_WATCH=0` — disable the watcher.
- `OSH_URL_WATCH_TIMEOUT=<seconds>` — override the 120 s timeout.
- Skipped automatically for `--dry-run`, Odoo subcommands (`shell`,
  `neutralize`, ...), `--no-http` and `--version`/`--help`.

Requires `osh` >= 1.1 (handler subclassing via `osh.handlers`, params as
`run()` decorators).

## How it works

- `UrlWatch` subclasses the `odoo` handler (`OdooRun`) and is declared via
  `extends = ["odoo"]` in `osh-plugin.toml` — the plugin imports lazily,
  only when `osh odoo` actually runs. It injects `--open` and
  `--url-watch/--no-url-watch` at parse time (decorators on `run()`) and runs
  `pre_env` right before `Backend.env()` execs — it resolves the port and
  spawns the sidecar.
- The sidecar is the hidden `osh echohttp PORT [DBNAME]` command — declared
  with `hidden = true` in `osh-plugin.toml`, so it never shows in `--help`.

## Layout

```
osh_echohttp/
├── osh-plugin.toml  # description + extends = ["odoo"] + hidden [commands]
├── __init__.py      # re-exports UrlWatch and EchoHttp for discovery
├── commands.py      # hidden `osh echohttp` sidecar command
├── watcher.py       # UrlWatch handler, port resolution, TCP polling
└── tests/
```
