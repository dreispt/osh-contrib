"""Kiri engine addressing, environment scoping and probing.

The Kiri engine speaks the Docker Engine API on its own socket, so every
``docker``/``docker compose`` call the ``kiri`` runtime makes runs with
``DOCKER_HOST`` pointed at it and ``DOCKER_CONTEXT`` dropped — scoped to
the runtime's own calls and restored afterwards (see ``kiri_engine``).
"""

import json
import os
import sys
from contextlib import contextmanager

from osh.common import run_subprocess

#: ``docker version --format`` probe whose ``.Server.Components`` list a
#: Kiri engine marks with a ``{"Name": "Kiri", "Version": ...}`` entry.
_PROBE_FORMAT = "{{json .Server}}"


def kiri_docker_host():
    """Return the Docker Engine address of the Kiri engine.

    ``$KIRI_SOCKET`` wins: a value already containing ``://`` is used
    verbatim, anything else is a socket path exposed as ``unix://<path>``.
    Otherwise the platform default applies — ``~/.kiri/run/docker.sock``
    on macOS, ``npipe:////./pipe/kiri`` on Windows and
    ``/run/kiri/docker.sock`` elsewhere.
    """
    socket = os.environ.get("KIRI_SOCKET")
    if socket:
        if "://" in socket:
            return socket
        return f"unix://{socket}"
    if sys.platform == "darwin":
        return f"unix://{os.path.expanduser('~')}/.kiri/run/docker.sock"
    if sys.platform == "win32":
        return "npipe:////./pipe/kiri"
    return "unix:///run/kiri/docker.sock"


@contextmanager
def kiri_engine():
    """Point the process environment at the Kiri engine for the block.

    Sets ``DOCKER_HOST`` to :func:`kiri_docker_host` and drops
    ``DOCKER_CONTEXT`` — both restored exactly (including absence) on
    exit, so nested scopes and the ambient Docker environment are never
    disturbed. Re-entrant: a nested scope restores the outer scope's
    values.
    """
    host = kiri_docker_host()
    saved_host = os.environ.get("DOCKER_HOST")
    saved_context = os.environ.get("DOCKER_CONTEXT")
    os.environ["DOCKER_HOST"] = host
    os.environ.pop("DOCKER_CONTEXT", None)
    try:
        yield host
    finally:
        if saved_host is None:
            os.environ.pop("DOCKER_HOST", None)
        else:
            os.environ["DOCKER_HOST"] = saved_host
        if saved_context is None:
            os.environ.pop("DOCKER_CONTEXT", None)
        else:
            os.environ["DOCKER_CONTEXT"] = saved_context


def probe_engine():
    """Probe the Kiri engine; return ``(reachable, kiri_version)``.

    Runs ``docker version`` inside the engine scope. ``reachable`` is
    False when docker is missing, exits non-zero or answers unparseable
    JSON. ``kiri_version`` is the Kiri component's version, ``None`` when
    the engine answers but is not Kiri.
    """
    with kiri_engine():
        returncode, out, _ = run_subprocess(
            ["docker", "version", "--format", _PROBE_FORMAT]
        )
    if returncode != 0:
        return False, None
    try:
        server = json.loads(out)
    except ValueError:
        return False, None
    for component in server.get("Components") or []:
        if component.get("Name") == "Kiri":
            return True, str(component.get("Version") or "unknown")
    return True, None
