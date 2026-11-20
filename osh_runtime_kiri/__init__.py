"""osh_runtime_kiri — run Odoo Compose stacks on the Kiri container engine.

Provides the ``kiri`` runtime: like ``osh init docker`` but every Docker
call is scoped to the Kiri engine (``$KIRI_SOCKET``, or the platform
default socket), the project gets a ``*.kiri.localhost`` URL, and
``osh odoo --kiri-share`` publishes its Odoo port at a public HTTPS
link for the duration of the run.

The runtime subclasses osh's built-in ``DockerRuntime`` and ``osh odoo``
is extended in place; the plugin's surface is declared under
``[tool.osh]`` in ``pyproject.toml``, so this module is imported lazily —
only when the ``kiri`` runtime or ``osh odoo`` needs it.
"""

from .odoo import OdooKiriShare  # noqa: F401 — re-exported for discovery
from .runtimes import KiriRuntime  # noqa: F401 — re-exported for discovery
