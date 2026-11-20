# osh-runtime-kiri

Run Odoo in a Docker Compose stack on the [Kiri](https://runkiri.com)
container engine — a Docker-compatible engine that is dramatically faster
than Docker Desktop on macOS and adds first-class names and port sharing.

The `kiri` runtime is a thin layer over osh's `docker` runtime: the same
`.osh/docker.toml`, the same generated Compose stack, the same
`compose exec` workflow — but every `docker` call is scoped to Kiri's
engine instead of the machine's default Docker context.

## Install

```sh
pipx inject osh "osh-runtime-kiri @ git+https://github.com/dreispt/osh-contrib.git#subdirectory=osh_runtime_kiri"
```

Requires `osh >= 2.0.0` and [Kiri](https://runkiri.com) installed.

## Usage

```sh
osh init kiri [--domain NAME]
osh odoo
osh exec psql
osh stop
```

`osh init kiri` accepts every `osh init docker` option (`--service`,
`--port`, `--compose-file`, ...) plus `--domain`. The project is reachable
at `http://<domain>.kiri.localhost`, where `<domain>` is `--domain` when
given, the stored `kiri_domain`, or the project directory name
normalised (`My_Project` → `my-project`).

### Engine address

Kiri's engine address defaults per platform:

- macOS: `unix://~/.kiri/run/docker.sock`
- Linux and other Unix: `unix:///run/kiri/docker.sock`
- Windows: `npipe:////./pipe/kiri`

Set `KIRI_SOCKET` to override — a socket path (`/path/to/docker.sock`)
becomes `unix:///path/to/docker.sock`; a value already containing `://`
(e.g. `tcp://host:2375`) is used verbatim. The targeting is scoped to the
`kiri` runtime's own calls: `DOCKER_HOST` is set and `DOCKER_CONTEXT`
dropped for them, and the process environment is restored afterwards, so
your global Docker context is never touched.

### Sharing

```sh
osh odoo --kiri-share [--kiri-share-name NAME]
```

Makes the running Odoo **publicly available on the Internet** through
[Kiri Share](https://runkiri.com): `kiri share <port> --json` starts in
the background before Odoo and prints `Odoo (public):
https://<name>.runkiri.cloud` — anyone who has the address can open the
Odoo instance, its login page and whatever data the database holds. Use
it to test webhooks, show a demo or open Odoo on a phone; share only
databases you would show anyone.

The share lives exactly as long as the Odoo run — it ends when Odoo
ends, including when `osh odoo` replaces itself with the Odoo process —
and the local port and `*.kiri.localhost` URL keep working while it
runs.

`--kiri-share-name NAME` reserves `NAME.runkiri.cloud` and implies
`--kiri-share`. `<port>` is the `-p/--http-port` value, else the
project's Odoo port. `--dry-run` previews the command. Runs that serve
no HTTP (`osh odoo shell`, `--no-http`, `--stop-after-init`) ignore the
option with a warning. Not supported on Windows yet.

Requires the `kiri` CLI — <https://runkiri.com/download> — and a Kiri
Cloud sign-in (`kiri share login`).
