# osh_echohttp

Prints the browser URL once `osh odoo` is actually ready to serve requests:

```bash
osh odoo           # prints "🚀 Odoo ready: http://mydb.localhost:8069" when up
osh odoo --open    # also opens the URL in your browser
```

Since `osh odoo` replaces itself with the Odoo process (`exec`), the plugin
spawns a detached `osh _watch-url` sidecar that TCP-polls the HTTP port and
writes to the same terminal — the line interleaves with Odoo's own log
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

Requires an `osh` core with operation extensions (osh >= 1.0).

## How it works

- `@extends("odoo")` mixin `UrlWatch` injects `--open` and
  `--url-watch/--no-url-watch` into `osh odoo` at parse time
  (`get_options`) and runs `pre_env` right before `Backend.env()` execs —
  it resolves the port and spawns the sidecar.
- `OSH_PLUGIN_MANIFEST["commands"]` declares the hidden `osh _watch-url`
  command the sidecar runs.

## Layout

```
osh_echohttp/
├── __init__.py   # OSH_PLUGIN_MANIFEST (commands + hooks)
├── commands.py   # hidden `osh _watch-url` command
├── watcher.py    # port resolution, TCP polling, sidecar spawn
└── tests/
```
