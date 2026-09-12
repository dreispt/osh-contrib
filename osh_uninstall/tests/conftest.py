"""Fixtures for the ``osh_uninstall`` test suite."""

import subprocess
import uuid

import pytest


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch):
    """Remove Osh-managed variables from the ambient environment.

    ``PG*`` variables are kept: they may be required to reach the test
    PostgreSQL server.
    """
    for var in ("VIRTUAL_ENV", "ODOO_RC"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def tmp_project(tmp_path):
    """Return a temporary project directory with a .osh marker and .git."""
    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)
    (project / ".osh").mkdir(parents=True, exist_ok=True)
    (project / ".git").mkdir(parents=True, exist_ok=True)
    return project


@pytest.fixture
def in_project(monkeypatch, tmp_project):
    """Switch into the temporary project for project-aware commands."""
    monkeypatch.chdir(tmp_project)
    return tmp_project


def _psql(db_name, sql):
    subprocess.run(["psql", "-d", db_name, "-c", sql], check=True)


@pytest.fixture
def pg_db():
    """Create uniquely-named real PostgreSQL databases, dropped on teardown.

    A local PostgreSQL server is assumed to be available. Names use a random
    ``osh-test-`` prefix so they can never collide with real databases on a
    shared development server. Plain ``createdb``/``dropdb``/``psql`` calls are
    used so project ``.odoorc`` credentials do not affect test databases.
    """
    try:
        probe = subprocess.run(
            ["psql", "-d", "postgres", "-c", "SELECT 1"], capture_output=True
        )
        available = probe.returncode == 0
    except FileNotFoundError:
        available = False
    if not available:
        pytest.skip("local PostgreSQL not available")

    created = []

    class _PgDb:
        @staticmethod
        def name():
            """Return a unique database name (not created)."""
            return f"osh-test-{uuid.uuid4().hex[:16]}"

        def create(self, name=None):
            """Create a real database and return its name."""
            name = name or self.name()
            try:
                subprocess.run(["createdb", name], check=True, capture_output=True)
            except (FileNotFoundError, subprocess.CalledProcessError) as exc:
                pytest.skip(f"local PostgreSQL not available: {exc}")
            created.append(name)
            return name

        def make_odoo_db(self, name=None, modules=()):
            """Create a database with stub Odoo module tables.

            ``modules`` is an iterable of ``(name, state)`` rows inserted into
            a minimal ``ir_module_module`` table. Returns the database name.
            """
            name = self.create(name)
            _psql(
                name,
                "CREATE TABLE ir_module_module "
                "(id serial, name varchar, state varchar)",
            )
            _psql(
                name,
                "CREATE TABLE ir_module_module_dependency "
                "(module_id int, name varchar)",
            )
            for mod_name, state in modules:
                _psql(
                    name,
                    "INSERT INTO ir_module_module (name, state) "
                    f"VALUES ('{mod_name}', '{state}')",
                )
            return name

        def psql(self, name, sql):
            """Run a SQL statement against a tracked database."""
            _psql(name, sql)

        def query(self, name, sql):
            """Run a query and return stripped stdout."""
            return subprocess.run(
                ["psql", "-d", name, "-t", "-A", "-c", sql],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()

    yield _PgDb()

    for name in created:
        # ``--if-exists`` and the osh-test- prefix guarantee we only ever
        # drop databases created by this fixture.
        subprocess.run(["dropdb", "--if-exists", name], capture_output=True)


@pytest.fixture
def capture_uninstall(monkeypatch, pg_db):
    """Replace ``core.run_uninstall`` with a recorder and state simulator.

    The fake marks the requested modules ``uninstalled`` — like the real
    ``button_immediate_uninstall`` would — unless ``dry_run`` is passed,
    so the command's post-run verification behaves realistically.
    """
    from osh_uninstall import core

    calls = []

    def _fake(modules, db_name, **kwargs):
        calls.append((modules, db_name, kwargs))
        if kwargs.get("dry_run"):
            return 0
        quoted = ", ".join(f"'{m}'" for m in modules)
        pg_db.psql(
            db_name,
            "UPDATE ir_module_module SET state='uninstalled' "
            f"WHERE name IN ({quoted})",
        )
        return 0

    monkeypatch.setattr(core, "run_uninstall", _fake)
    return calls
