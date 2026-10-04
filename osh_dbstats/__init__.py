"""osh_dbstats — diagnose an Odoo database from the command line.

Provides ``osh db stats``, a read-only dashboard of a database's size,
bloat, index usage and live activity (with ``pg_stat_statements`` slow
query stats when the extension is enabled), and ``osh db vacuum``, a
``VACUUM ANALYZE`` maintenance command for the whole database or selected
tables.

Both commands read the target database through ``psql`` run via
``osh.db.run_in_backend``, so they work identically on host and Docker
backends. They are declared under ``[tool.osh]`` in ``pyproject.toml``,
so this module is imported lazily — only when the commands actually run.
"""

from .commands import DbStats, DbVacuum  # noqa: F401 — re-exported for discovery
