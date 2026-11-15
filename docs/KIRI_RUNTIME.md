# Kiri runtime — spec

**Status:** in progress (PR #26)
**Date:** 2026-11-14
**Scope:** osh-contrib — new plugin `osh_runtime_kiri` (runtime `kiri`,
option `osh odoo --kiri-share`).
**Related:** osh core `docs/DOCKER.md` and the built-in
`osh_runtime_docker` plugin own the Compose execution model this runtime
reuses; `docs/PLUGINS.md` owns the plugin contract.

## Context

[Kiri](https://runkiri.com) is a small, fast container runtime for Mac,
Linux and Windows. It serves the Docker Engine API on its own socket, so
the `docker` CLI and Compose work against it unchanged.

Kiri adds what plain Docker lacks for local development:

- every container answers by name, e.g. `http://web.kiri.localhost`;
- the `dev.kiri.domain` and `dev.kiri.http.port` labels pick that name
  and the container port it reaches;
- `kiri share PORT` gives a local port a public HTTPS link.

Facts this spec relies on (docs.runkiri.com, Kiri 0.2.1):

- The engine socket is `~/.kiri/run/docker.sock` on macOS and
  `/run/kiri/docker.sock` on Linux. Windows serves the `\\.\pipe\kiri`
  named pipe. `KIRI_SOCKET` overrides the location.
- `DOCKER_HOST` wins over any docker context. Kiri's own `kiri` wrapper
  sets `DOCKER_HOST` and removes `DOCKER_CONTEXT`.
- `docker version` against Kiri lists a server component named `Kiri`.
- `<name>.kiri.localhost` needs no setup on macOS and Linux.
  `.kiri.local` needs an admin step and does not exist on Linux.

osh users already run Odoo in Compose stacks with the `docker` runtime.
The goal: the same workflow, on Kiri's engine, with Kiri's names and
sharing — without the user picking a docker context by hand.

## Spec

### A. Engine targeting

- **A1.** Every `docker`/`docker compose` process the `kiri` runtime
  starts runs with `DOCKER_HOST` set to Kiri's engine and without
  `DOCKER_CONTEXT`. This covers `osh init kiri`, `osh odoo`/`osh exec`,
  the database helpers (`osh db ...`) and `osh stop`.
- **A2.** The engine address is resolved as:
  1. `$KIRI_SOCKET` — used verbatim when it contains `://`, otherwise
     as a socket path (`unix://<path>`);
  2. macOS: `unix://$HOME/.kiri/run/docker.sock`;
  3. Windows: `npipe:////./pipe/kiri`;
  4. any other platform: `unix:///run/kiri/docker.sock`.
- **A3.** The targeting is scoped to the `kiri` runtime's own calls. The
  osh process environment is restored afterwards. Example: in
  `osh stop --all` the `docker` runtime's own `docker ps` still runs
  without the Kiri `DOCKER_HOST`.
- **A4.** `osh init kiri` checks the engine before writing anything:
  - unreachable → error naming the engine address, with the hint to
    start Kiri or set `KIRI_SOCKET`; `.osh/docker.toml` is not written;
  - reachable but no `Kiri` server component → warning that the engine
    is not Kiri, then init continues;
  - `--dry-run` skips the check and reports the engine address it would
    use.
- **A5.** The runtime's init-phase diagnostics report the engine, so
  `osh init kiri` prints `Kiri <version> at <address>` (a note), or the
  not-Kiri warning. (osh 2.0 has no `osh doctor` command.)

### B. Names

- **B1.** The Odoo service gets two labels through osh's generated
  Compose override (`.osh/docker-compose.osh.yml`):
  - `dev.kiri.http.port`: the container port Odoo serves HTTP on —
    `8069`, or the `osh odoo -p <n>` port when one is requested;
  - `dev.kiri.domain`: the project's Kiri domain.
- **B2.** The project domain is:
  - `kiri_domain` from `.osh/docker.toml`, set by
    `osh init kiri --domain NAME` and kept on re-init without the flag;
  - otherwise the environment root directory's name, lowercased, with
    each run of characters outside `[a-z0-9-]` replaced by `-`, and
    leading/trailing `-` stripped (`My_Project` → `my-project`).
  - `--domain` must match `[a-z0-9]([a-z0-9.-]*[a-z0-9])?`; anything
    else is a usage error before any change.
- **B3.** A server run prints `Odoo: http://<domain>.kiri.localhost` to
  stderr: `osh odoo`, or `osh exec odoo` whose first argument is absent
  or an option (`osh exec odoo -d mydb`). Other commands (`osh exec`,
  `osh exec odoo shell`, `osh exec ls`, db helpers) do not.
- **B4.** A successful `osh init kiri` ends by printing the same URL.

### C. Sharing — `osh odoo --kiri-share`

`osh odoo` serves Odoo on this computer only. `--kiri-share` also makes
it publicly available on the Internet for as long as Odoo runs: anyone
with the `*.runkiri.cloud` address can open it (webhooks, demos,
phones). The local port keeps working: Kiri Share forwards visits from
its edge to the local port, it does not take the port over. The option
help says the instance becomes public.

- **C1.** `osh odoo --kiri-share` starts `kiri share <port> --json` in
  the background before Odoo starts, waits for the share to go live
  (`live` event, at most 30 s), prints
  `Odoo (public): https://<...>.runkiri.cloud` to stderr, then starts
  Odoo as usual. `<port>` is the `-p/--http-port` value given to
  `osh odoo`, else the active runtime's `odoo_port`, else 8069. It works
  for any runtime, not only `kiri`.
- **C2.** `--kiri-share-name NAME` adds `--name NAME` (reserves
  `NAME.runkiri.cloud`) and implies `--kiri-share`.
- **C3.** The share ends when Odoo ends — also when `osh odoo` replaced
  itself with the Odoo process — and never outlives it.
- **C4.** With `--dry-run`, it prints
  `Would share: kiri share <port> --json ...` and starts nothing.
- **C5.** Without `kiri` on `PATH`, `osh odoo` fails before starting Odoo,
  with an error pointing to `https://runkiri.com/download`. When the
  share ends or fails before going live (not signed in, no connection,
  timeout), `osh odoo` fails before starting Odoo with Kiri's last
  message and the hint to sign in with `kiri share login`.
- **C6.** Runs that serve no HTTP (a subcommand such as `osh odoo shell`,
  `--no-http`, `--stop-after-init`, `--help`, `--version`) warn that
  `--kiri-share` is ignored and start no share.

### D. Packaging

- **D1.** The plugin ships as `osh_runtime_kiri` with its own
  `pyproject.toml`: entry point `osh_runtime_kiri`, `[tool.osh]`
  declaring the `kiri` runtime, `extends = ["odoo"]` (for `--kiri-share`),
  `depends = ["osh-runtime-docker"]` and `min_osh = "2.0.0"`.
- **D2.** It is listed in the root bundle's entry points, `plugins.txt`
  and the root `README.md`, and has its own `README.md`.

## Contract details

- `--kiri-share`: the plugin extends the `odoo` handler (`OdooRun`) and
  starts the share in `pre_env()`. The share runs under a small
  supervisor process (`python -m osh_runtime_kiri.share`) that:
  - runs `kiri share <port> --json [--name NAME]` and reads its event
    lines; the public URL is the first `https://` string value in the
    `live` event (Kiri does not document the event fields);
  - reports one line on its stdout — `live <url>` or `error <message>` —
    then stops writing to that pipe, so it survives `osh` exec'ing Odoo;
  - holds the read end of a pipe whose write end `osh` marks inheritable,
    so the Odoo process inherits it across `execvp`; EOF on that pipe
    (Odoo and everything holding the write end exited) stops `kiri`.
    The supervisor runs in its own session, so Ctrl+C reaches Odoo, not
    the share; the share ends through C3.
- `KiriRuntime` subclasses osh's built-in `DockerRuntime`. Everything not
  listed here behaves as the `docker` runtime: `.osh/docker.toml`, the
  generated stack, `compose exec`, fingerprinted builds, ports.
- The runtime's public entry points run inside one engine scope that
  sets `DOCKER_HOST`, drops `DOCKER_CONTEXT`, and restores both on exit:
  `init`, `diagnose`, `detect_odoo_version`, `env`, `db_env`, `status`,
  `stop`, `stop_report`, `stop_by_name`, `stop_all`,
  `port_holder_entries`.
  - `env()` may `execvp` docker; the scope is still active then, so the
    replaced process inherits the Kiri `DOCKER_HOST`.
- The engine probe is
  `docker version --format '{{json .Server}}'`; the `Kiri` component's
  `Version` is the Kiri version.
- `.osh/docker.toml` gains one optional key: `kiri_domain`.
- Coupling: the plugin imports `osh.plugins.osh_runtime_docker`, which is
  not part of osh's public plugin API. `min_osh` pins the release whose
  Docker runtime hooks it overrides (`_validate_init_stack`,
  `_prepare_compose_override`, `_prepare_docker_config`).

## Alternatives considered

- **Point users at `docker context use kiri`.** Rejected: it switches
  every tool on the machine, the context may not exist (`kiri-lite` on
  Linux), and osh could not tell which engine a project belongs to.
- **`compose_tool = "docker --context kiri compose"` in docker.toml.**
  Rejected: covers Compose calls only. Plain `docker` calls (container
  listing for `osh stop`, the engine probe) would still hit the default
  engine, and it needs the `kiri` context to exist.
- **Set `DOCKER_HOST` once when the runtime is instantiated.** Rejected:
  `osh stop --all` instantiates every runtime in one process, so the
  `docker` runtime would silently target Kiri too.
- **A Kiri Linux machine (`kiri machine create`) running the venv
  runtime.** Rejected for now: a second, heavier execution model; the
  Compose model already gets Kiri's speed, names and sharing.
- **A separate `osh kiri share` command.** Replaced by
  `osh odoo --kiri-share`: one terminal and one Ctrl+C, and the public
  link cannot outlive the server it exposes.
- **A plain `--share` option.** Rejected: every plugin adds options to
  the same `osh odoo`, so a generic name could collide with another
  tunnel plugin or a future core option; `--kiri-share` also says it
  needs Kiri and goes through an outside service.
- **Watch Odoo's PID to end the share.** Rejected: `os.kill(pid, 0)`
  terminates the process on Windows. A pipe whose write end Odoo
  inherits ends the share on EOF on every platform.
- **Share by container name (`kiri share <container>`).** Rejected:
  Windows only shares ports, and a port works for every osh runtime.
- **Use `.kiri.local` names.** Rejected: needs an admin step on macOS
  and does not exist on Linux; `.kiri.localhost` works everywhere.

## Tasks

- [x] Spec
- [x] Acceptance tests (failing first)
- [x] Plugin skeleton, packaging, README
- [x] Engine targeting (A1–A5)
- [x] Names (B1–B4)
- [x] `osh odoo --kiri-share` (C1–C6), replacing `osh kiri share`
- [x] Green suite, pre-commit, PR (#26)
- [x] Green suite after `--kiri-share`
