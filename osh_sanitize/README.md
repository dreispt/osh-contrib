# osh_sanitize

Scrub a database for development use: `osh db sanitize` anonymizes PII
with deterministic placeholders and trims low-value rows from big
tables. `osh db restore --anonymize --trim` runs the same steps
after neutralizing a restored dump.

## `osh db sanitize`

```
osh db sanitize [GROUP…] [-d DB] [--force] [--dry-run] [--list]
                [--no-anonymize] [--no-trim] [--keep-days N]
                [--script NAME…] [--skip NAME…] [--var NAME=VALUE…]
                [--vacuum]
```

Two groups run by default:

- **anonymize** — rewrites personal data (partners, users, bank
  accounts, employees, chatter) with deterministic placeholders. The bundled
  profile splits into the `identity` and `address` levels, selectable
  as positional groups.
- **trim** — deletes rows from big, low-value tables (logs, mail
  queues, old chatter) following a bundled watchlist.

The database must exist and should look neutralized — the command
warns and asks for confirmation otherwise (`--force` skips the prompt,
`--dry-run` previews without writing).

## Scripts resolve in layers

Anonymize and trim steps are plain `*.sql` files resolved at run time:

1. bundled defaults shipped with the plugin,
2. `~/.config/osh/<kind>/` — centrally maintained, all projects,
3. `.osh/<kind>/` — project-specific.

A same-named file in a later layer overrides. `--list` shows the
resolved set with its source layer; `--script`/`--skip` select from
the combined set of both groups. `:keep_days` inside trim scripts
comes from `--keep-days`, `$OSH_KEEP_DAYS`, or the
`[trim] keep_days` project setting.

## `osh db restore --anonymize --trim`

The plugin extends both restore spellings. The flags require an Osh
project and run after the restore and any neutralization. They are
skipped under `--dry-run`. A sanitization failure exits nonzero and
leaves the restored database in place.

## Install

Requires osh 2.1.0 or later.

```
pipx inject osh "osh-sanitize @ git+https://github.com/dreispt/osh-contrib.git#subdirectory=osh_sanitize"
```
