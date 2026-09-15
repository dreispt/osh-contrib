"""Fixtures for the ``osh_update`` test suite."""

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


@pytest.fixture
def module_dir(tmp_project):
    """Return a factory creating a project module directory with a manifest."""

    def _make(name, files=None):
        module = tmp_project / name
        module.mkdir(parents=True, exist_ok=True)
        (module / "__manifest__.py").write_text(
            f"{{'name': '{name}', 'version': '1.0'}}\n"
        )
        for rel, content in (files or {}).items():
            path = module / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        return module

    return _make


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
            """Create a database with stub Odoo module/config tables.

            ``modules`` is an iterable of ``(name, state)`` rows inserted into
            a minimal ``ir_module_module`` table. Returns the database name.
            """
            name = self.create(name)
            _psql(name, "CREATE TABLE ir_module_module (name varchar, state varchar)")
            _psql(
                name,
                "CREATE TABLE ir_config_parameter " "(key varchar UNIQUE, value text)",
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
def capture_update(monkeypatch):
    """Replace ``core.run_update`` with a recorder; returns the calls list."""
    from osh_update import core

    calls = []
    monkeypatch.setattr(
        core,
        "run_update",
        lambda modules, db_name, **kwargs: calls.append((modules, db_name, kwargs))
        or 0,
    )
    return calls
