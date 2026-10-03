"""osh_migrations — collect module ``migrations/`` scripts across branches.

Each OCA repository branch ships only the migration scripts for its own
version, so upgrading a database across several versions (17.0 → 19.0) is
missing the scripts from the versions in between. ``osh
collect-migrations`` scans a directory for git repositories, checks out
every ``N.N`` version branch in a temporary ``git worktree``, and copies
each module's ``migrations/`` directory into a ``migration/`` tree that
mirrors the scanned layout — ready to be merged back over the addons
directories before running ``-u all``.

"""

from .commands import CollectMigrations  # noqa: F401 — re-exported for discovery
