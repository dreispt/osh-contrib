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


def _psql_argv(db_name, variables=None, extra=()):
    """Build a ``psql`` argv, passing *variables* as ``-v key=value``.

    Statements reference them as ``:'key'`` so psql quotes them as SQL
    literals — the same mechanism the plugin's own store module uses, so
    test data containing quotes can never break the statement.

    The SQL itself is piped through stdin rather than ``-c``: psql only
    interpolates variables into input read from stdin or a file.
    ``ON_ERROR_STOP`` makes it exit non-zero on SQL errors, which ``-c``
    would do implicitly.
    """
    argv = ["psql", "-d", db_name, "-v", "ON_ERROR_STOP=1", *extra]
    for key, value in (variables or {}).items():
        argv += ["-v", f"{key}={value}"]
    return argv


def _psql(db_name, sql, variables=None):
    subprocess.run(_psql_argv(db_name, variables), input=sql, text=True, check=True)


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
                    "VALUES (:'mod', :'state')",
                    {"mod": mod_name, "state": state},
                )
            return name

        def psql(self, name, sql, variables=None):
            """Run a SQL statement against a tracked database."""
            _psql(name, sql, variables)

        def query(self, name, sql, variables=None):
            """Run a query and return stripped stdout."""
            return subprocess.run(
                _psql_argv(name, variables, extra=("-t", "-A")),
                input=sql,
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
        placeholders = ", ".join(f":'mod{i}'" for i in range(len(modules)))
        pg_db.psql(
            db_name,
            "UPDATE ir_module_module SET state='uninstalled' "
            f"WHERE name IN ({placeholders})",
            {f"mod{i}": m for i, m in enumerate(modules)},
        )
        return 0

    monkeypatch.setattr(core, "run_uninstall", _fake)
    return calls
