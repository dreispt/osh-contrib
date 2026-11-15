"""Kiri runtime — Docker Compose stacks on the Kiri container engine."""

import functools
import re

import click
from osh import echo
from osh.common import env_root
from osh.plugins.osh_runtime_docker.runtimes import DockerRuntime
from osh.plugins.osh_runtime_docker.utils import _load_docker_config

from .engine import kiri_docker_host, kiri_engine, probe_engine

_DOMAIN_RE = re.compile(r"[a-z0-9]([a-z0-9.-]*[a-z0-9])?")


def _on_kiri_engine(func):
    """Run a runtime entry point with the env scoped to the Kiri engine."""

    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        with kiri_engine():
            return func(self, *args, **kwargs)

    return wrapper


class KiriRuntime(DockerRuntime):
    """Run the project's Compose stack on the Kiri engine (runkiri.com)."""

    name = "kiri"
    label = "Kiri"
    description = (
        "Run Odoo in a Compose stack on the Kiri container engine — the "
        "same stack as the docker runtime, targeted at Kiri's engine."
    )
    help_text = (
        "Like ``osh init docker``, but every Docker call is scoped to the "
        "Kiri engine: ``$KIRI_SOCKET`` when set, otherwise the platform "
        "default socket. The project is reachable at "
        "``http://<domain>.kiri.localhost`` and ``osh odoo --kiri-share`` "
        "publishes its Odoo port at a public HTTPS link while it runs.\n\n"
        "Requires Kiri (https://runkiri.com)."
    )

    @classmethod
    def get_init_options(cls):
        return [
            *super().get_init_options(),
            click.Option(
                ["--domain"],
                callback=_validate_domain,
                help="Kiri domain for this project (default: derived from "
                "the project directory name).",
            ),
        ]

    @_on_kiri_engine
    def init(self, target, *, dry_run=False, **options):
        self._kiri_domain = options.get("domain")
        result = super().init(target, dry_run=dry_run, **options)
        if result and not dry_run:
            echo.info(
                "Odoo will answer at "
                f"http://{_project_domain(target)}.kiri.localhost"
            )
        return result

    @_on_kiri_engine
    def diagnose(self, base, ctx=None, *, sections=None, **options):
        diagnostics = super().diagnose(base, ctx, sections=sections, **options)
        if options.get("phase") == "init" and not _init_dry_run(ctx, options):
            self._report_engine(diagnostics)
        return diagnostics

    def _report_engine(self, diagnostics):
        """Add the engine probe outcome to init-phase diagnostics."""
        reachable, version = self._probe_engine()
        address = kiri_docker_host()
        if not reachable:
            diagnostics.add_error(
                f"Kiri engine unreachable at {address}. "
                "Start Kiri, or set KIRI_SOCKET to its engine socket."
            )
        elif version is None:
            diagnostics.add_warning(
                f"The engine at {address} is not Kiri; "
                "check KIRI_SOCKET or start Kiri."
            )
        else:
            diagnostics.add_note(f"Kiri {version} at {address}")
        self._engine_reported = True

    def _probe_engine(self):
        """Return the cached engine probe, probing on first use."""
        cached = getattr(self, "_engine_probe", None)
        if cached is None:
            cached = probe_engine()
            self._engine_probe = cached
        return cached

    @_on_kiri_engine
    def detect_odoo_version(self, *args, **kwargs):
        return super().detect_odoo_version(*args, **kwargs)

    @_on_kiri_engine
    def env(self, ctx, base, env_spec, *, dry_run=False, **options):
        if _is_odoo_server_run(env_spec.argv):
            echo.info(
                f"Odoo: http://{_project_domain(base)}.kiri.localhost",
                err=True,
            )
        return super().env(ctx, base, env_spec, dry_run=dry_run, **options)

    @_on_kiri_engine
    def db_env(self, *args, **kwargs):
        return super().db_env(*args, **kwargs)

    @_on_kiri_engine
    def status(self, *args, **kwargs):
        return super().status(*args, **kwargs)

    @_on_kiri_engine
    def stop(self, *args, **kwargs):
        return super().stop(*args, **kwargs)

    @_on_kiri_engine
    def stop_report(self, *args, **kwargs):
        return super().stop_report(*args, **kwargs)

    @_on_kiri_engine
    def stop_by_name(self, *args, **kwargs):
        return super().stop_by_name(*args, **kwargs)

    @_on_kiri_engine
    def stop_all(self, *args, **kwargs):
        return super().stop_all(*args, **kwargs)

    @_on_kiri_engine
    def port_holder_entries(self, *args, **kwargs):
        return super().port_holder_entries(*args, **kwargs)

    @_on_kiri_engine
    def build_addons_paths(self, *args, **kwargs):
        return super().build_addons_paths(*args, **kwargs)

    @_on_kiri_engine
    def odoo_data_dir(self, *args, **kwargs):
        return super().odoo_data_dir(*args, **kwargs)

    def _validate_init_stack(self, target, compose_file, service, *, dry_run=False):
        """Probe the Kiri engine before init writes the project config."""
        if dry_run:
            echo.info(f"Kiri engine: {kiri_docker_host()} (not probed in dry run)")
            return super()._validate_init_stack(
                target, compose_file, service, dry_run=dry_run
            )
        reachable, version = self._probe_engine()
        address = kiri_docker_host()
        if not reachable:
            raise click.ClickException(
                f"Kiri engine unreachable at {address}. "
                "Start Kiri, or set KIRI_SOCKET to its engine socket."
            )
        if version is None and not getattr(self, "_engine_reported", False):
            echo.warning(
                f"The engine at {address} is not Kiri; "
                "check KIRI_SOCKET or start Kiri."
            )
        return super()._validate_init_stack(
            target, compose_file, service, dry_run=dry_run
        )

    def _write_docker_config(self, target, **values):
        """Persist ``.osh/docker.toml`` with the Kiri domain carried over."""
        domain = getattr(self, "_kiri_domain", None) or (
            _load_docker_config(target) or {}
        ).get("kiri_domain")
        if domain:
            values["kiri_domain"] = domain
        super()._write_docker_config(target, **values)

    def _prepare_compose_override(self, base, service, port=None, compose_file=None):
        """Add the ``dev.kiri.*`` labels naming the service for Kiri."""
        content = super()._prepare_compose_override(
            base, service, port=port, compose_file=compose_file
        )
        labels = (
            "    labels:\n"
            f'      dev.kiri.http.port: "{port or 8069}"\n'
            f'      dev.kiri.domain: "{_project_domain(base)}"\n'
        )
        if content is None:
            return (
                "# Generated by osh — overrides for the project's Compose stack.\n"
                "# Do not edit; regenerated on each run.\n"
                "services:\n"
                f"  {service}:\n" + labels
            )
        marker = f"  {service}:\n"
        return content.replace(marker, marker + labels, 1)


def _project_domain(base):
    """Return the project's Kiri domain (spec B2).

    ``kiri_domain`` in ``.osh/docker.toml`` wins; otherwise the env root
    directory name is slugged — lowercased, runs of characters outside
    ``[a-z0-9-]`` collapsed to ``-`` and edge dashes stripped.
    """
    domain = (_load_docker_config(base) or {}).get("kiri_domain")
    if domain:
        return domain
    slug = re.sub(r"[^a-z0-9-]+", "-", env_root(base).name.lower()).strip("-")
    return slug or "odoo"


def _is_odoo_server_run(argv):
    """Return True when *argv* is an Odoo server invocation (spec B3).

    ``odoo``/``odoo-bin`` with no subcommand — Odoo takes its subcommand
    first, so the server runs when the first argument is absent or a flag
    (``odoo -d db --dev=all``); ``odoo shell`` is not a server run.
    """
    argv = list(argv or [])
    if not argv or argv[0] not in ("odoo", "odoo-bin"):
        return False
    return len(argv) == 1 or argv[1].startswith("-")


def _init_dry_run(ctx, options):
    """Return True when the init invocation is a dry run.

    ``runtime.init`` sees ``dry_run`` but ``runtime.diagnose`` does not —
    the flag is recovered from the Click context's params instead.
    """
    if options.get("dry_run"):
        return True
    params = getattr(ctx, "params", None) or {}
    return bool(params.get("dry_run"))


def _validate_domain(ctx, param, value):
    """Click callback enforcing the Kiri domain grammar (spec B2)."""
    if value is not None and not _DOMAIN_RE.fullmatch(value):
        raise click.BadParameter(
            f"'{value}' is not a valid Kiri domain — use letters, digits, "
            "'.' and '-' (e.g. my-shop or shop.example.com)."
        )
    return value
