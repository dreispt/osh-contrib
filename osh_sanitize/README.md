# osh_sanitize

Prepare an internal development copy: `osh db sanitize` masks selected
personal data and trims low-value rows from big tables.
`osh db restore --anonymize --trim` runs the same steps after neutralizing
a restored dump.

## `osh db sanitize`

```
osh db sanitize [GROUP…] [--db DB] [--force] [--dry-run] [--list]
                [--no-anonymize] [--no-trim] [--keep-days N]
                [--script NAME…] [--skip NAME…] [--var NAME=VALUE…]
                [--vacuum]
```

Two groups run by default:

- **anonymize** — partially masks partner and company names (for example,
  `Jane Doe` becomes `J*** D***`). Record IDs, relationships, and internal
  user logins and account names stay unchanged; portal user logins are
  masked. The bundled profile splits into the `identity` and `address`
  levels, selectable as positional groups.
- **trim** — deletes rows from big, low-value tables (logs, mail
  queues, old chatter) following a bundled watchlist.

**What stays recognizable:**

- Email keeps at most one initial and uses the non-deliverable
  `example.invalid` domain; core's `dev+<id>@example.local` fallback
  addresses keep no initial. Phone numbers keep at most the last four
  digits.
- Addresses keep city, state and country. Street names keep initials and
  postcodes keep at most the first two characters.
- Bank numbers keep at most four trailing characters in synthetic account
  numbers. Outgoing bank payments are disabled where supported.
- Payment tokens keep at most four display digits. Known provider references
  are replaced entirely, and tokens are archived where supported. Custom
  provider fields may need a project-specific masking script.

**Internal copies only:** masked names and unchanged user details can
still identify people. The legacy `database.is_anonymized` flag means
the full script set ran, not that the data is safe to share.

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
