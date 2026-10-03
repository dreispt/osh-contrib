"""Collect the data behind the ``osh db stats`` dashboard.

Every collector runs read-only catalog queries through
:mod:`osh_dbstats.store` and returns plain dictionaries and lists — the
renderer never sees SQL. Optional probes (``pg_stat_statements``, the
Odoo watchlist, the filestore size) degrade to ``None``/empty rather
than failing the report.
"""

from osh.db import resolve_backend, run_in_backend

from . import store

# Dead-tuple ratio above which a table is flagged as bloated.
BLOAT_RATIO_WARN = 0.15
BLOAT_RATIO_BAD = 0.30
# Minimum dead-tuple count before the ratio is meaningful.
BLOAT_MIN_DEAD = 1000

LONG_RUNNING_SECS = 30


def collect(base, db_name, *, top=10, filestore=True, ctx=None):
    """Collect the full report for *db_name*."""
    report = {"db_name": db_name, "top": top}
    report["overview"] = _overview(base, db_name, ctx=ctx)
    report["odoo_version"] = _odoo_version(base, db_name, ctx=ctx)
    report["filestore"] = _filestore_size(base, db_name, ctx=ctx) if filestore else None
    report["largest_tables"] = _largest_tables(base, db_name, top, ctx=ctx)
    report["bloated_tables"] = _bloated_tables(base, db_name, top, ctx=ctx)
    report["indexes"] = _indexes(base, db_name, top, ctx=ctx)
    report["activity"] = _activity(base, db_name, top, ctx=ctx)
    report["query_stats"] = _query_stats(base, db_name, top, ctx=ctx)
    return report


def _overview(base, db_name, ctx=None):
    """Return the single-row overview block."""
    rows = store.query(
        base,
        db_name,
        "SELECT pg_database_size(current_database()),"
        " current_setting('server_version'),"
        " (SELECT count(*) FROM pg_stat_user_tables),"
        " (SELECT COALESCE(sum(n_live_tup), 0) FROM pg_stat_user_tables),"
        " (SELECT EXTRACT(EPOCH FROM now() - stats_reset)::bigint"
        "  FROM pg_stat_database WHERE datname = current_database())",
        ctx=ctx,
    )
    size, server_version, tables, rows_est, stats_age = rows[0]
    return {
        "size_bytes": int(size),
        "server_version": server_version.split()[0],
        "table_count": int(tables),
        "row_count": int(rows_est),
        "stats_age_secs": int(stats_age) if stats_age else None,
    }


def _odoo_version(base, db_name, ctx=None):
    """Return the Odoo version of the database, or ``None`` for non-Odoo DBs."""
    rows = store.query_or_none(
        base,
        db_name,
        "SELECT latest_version FROM ir_module_module WHERE name = 'base'",
        ctx=ctx,
    )
    return rows[0][0] if rows else None


def _filestore_size(base, db_name, ctx=None):
    """Return ``{"path", "bytes"}`` for ``filestore/<db_name>``.

    ``path`` is the resolved filestore location (``None`` when the Odoo
    data dir cannot be determined); ``bytes`` is its size from ``du -sk``
    (POSIX; busybox ``du`` has no ``-b``) or ``None`` when the directory
    is missing or the probe failed.
    """
    result = {"path": None, "bytes": None}
    try:
        data_dir = resolve_backend(base).odoo_data_dir(base)
        if not data_dir:
            return result
        result["path"] = path = f"{data_dir}/filestore/{db_name}"
        returncode, stdout, _ = _du(base, path, ctx=ctx)
        if returncode != 0 or not stdout.strip():
            return result
        result["bytes"] = int(stdout.split()[0]) * 1024
    except Exception:
        pass
    return result


def _du(base, path, ctx=None):
    """Run ``du -sk`` on *path* inside the backend environment."""
    returncode, stdout, stderr = run_in_backend(ctx, base, ["du", "-sk", path])
    return returncode, stdout, stderr


def _largest_tables(base, db_name, top, ctx=None):
    """Return the *top* tables by total size."""
    rows = store.query(
        base,
        db_name,
        "SELECT relname, pg_total_relation_size(relid),"
        " pg_relation_size(relid), pg_indexes_size(relid), n_live_tup"
        " FROM pg_stat_user_tables"
        f" ORDER BY pg_total_relation_size(relid) DESC LIMIT {int(top)}",
        ctx=ctx,
    )
    return [
        {
            "name": name,
            "total_bytes": int(total),
            "table_bytes": int(table),
            "index_bytes": int(idx),
            "rows": int(live),
        }
        for name, total, table, idx, live in rows
    ]


def _bloated_tables(base, db_name, top, ctx=None):
    """Return tables with meaningful dead-tuple ratios, worst first."""
    rows = store.query(
        base,
        db_name,
        "SELECT relname, n_live_tup, n_dead_tup,"
        " EXTRACT(EPOCH FROM now() - GREATEST(last_vacuum, last_autovacuum))::bigint,"
        " EXTRACT(EPOCH FROM now() - GREATEST(last_analyze, last_autoanalyze))::bigint"
        " FROM pg_stat_user_tables"
        f" WHERE n_dead_tup > {BLOAT_MIN_DEAD}"
        " ORDER BY n_dead_tup::float / (n_live_tup + n_dead_tup) DESC"
        f" LIMIT {int(top)}",
        ctx=ctx,
    )
    bloated = []
    for name, live, dead, vacuum_age, analyze_age in rows:
        live, dead = int(live), int(dead)
        total = live + dead
        # Stale stats can report more dead tuples than the total estimate.
        ratio = min(dead / total, 1.0) if total else 0.0
        if ratio < BLOAT_RATIO_WARN:
            continue
        bloated.append(
            {
                "name": name,
                "live": live,
                "dead": dead,
                "ratio": ratio,
                "vacuum_age_secs": int(vacuum_age) if vacuum_age else None,
                "analyze_age_secs": int(analyze_age) if analyze_age else None,
            }
        )
    return bloated


def _indexes(base, db_name, top, ctx=None):
    """Return ``{"largest", "total_bytes", "count"}`` index reports."""
    totals = store.query(
        base,
        db_name,
        "SELECT COALESCE(sum(pg_relation_size(indexrelid)), 0), count(*)"
        " FROM pg_stat_user_indexes",
        ctx=ctx,
    )
    largest_rows = store.query(
        base,
        db_name,
        "SELECT indexrelname, relname, pg_relation_size(indexrelid), idx_scan"
        " FROM pg_stat_user_indexes"
        f" ORDER BY pg_relation_size(indexrelid) DESC LIMIT {int(top)}",
        ctx=ctx,
    )
    return {
        "total_bytes": int(totals[0][0]),
        "count": int(totals[0][1]),
        "largest": [
            {
                "name": name,
                "table": table,
                "bytes": int(size),
                "scans": int(scans),
            }
            for name, table, size, scans in largest_rows
        ],
    }


def _activity(base, db_name, top, ctx=None):
    """Return connections, long-running and blocked queries for the database."""
    counts = store.query_or_none(
        base,
        db_name,
        "SELECT"
        " (SELECT count(*) FROM pg_stat_activity"
        "  WHERE datname = current_database()),"
        " (SELECT count(*) FROM pg_stat_activity"
        "  WHERE backend_type = 'autovacuum worker'"
        "  AND datname = current_database()),"
        " current_setting('max_connections')::int",
        ctx=ctx,
    )
    states = store.query(
        base,
        db_name,
        "SELECT COALESCE(state, 'other'), count(*)"
        " FROM pg_stat_activity WHERE datname = current_database()"
        " GROUP BY 1 ORDER BY 2 DESC",
        ctx=ctx,
    )
    long_running = store.query(
        base,
        db_name,
        "SELECT pid, EXTRACT(EPOCH FROM now() - query_start)::bigint,"
        " left(regexp_replace(query, '\\s+', ' ', 'g'), 120)"
        " FROM pg_stat_activity"
        " WHERE datname = current_database() AND state = 'active'"
        " AND pid <> pg_backend_pid()"
        f" AND now() - query_start > interval '{LONG_RUNNING_SECS} seconds'"
        " ORDER BY query_start"
        f" LIMIT {int(top)}",
        ctx=ctx,
    )
    blocked = store.query(
        base,
        db_name,
        "SELECT a.pid, b.blocking_pid,"
        " EXTRACT(EPOCH FROM now() - a.query_start)::bigint,"
        " left(regexp_replace(a.query, '\\s+', ' ', 'g'), 120)"
        " FROM pg_stat_activity a"
        " CROSS JOIN LATERAL (SELECT unnest(pg_blocking_pids(a.pid)) AS blocking_pid) b"
        " WHERE a.datname = current_database()"
        f" LIMIT {int(top)}",
        ctx=ctx,
    )
    return {
        "connections": int(counts[0][0]) if counts else None,
        "autovacuum_workers": int(counts[0][1]) if counts else None,
        "max_connections": int(counts[0][2]) if counts else None,
        "states": {state: int(count) for state, count in states},
        "long_running": [
            {"pid": int(pid), "secs": int(secs), "query": query}
            for pid, secs, query in long_running
        ],
        "blocked": [
            {
                "pid": int(pid),
                "blocking_pid": int(blocking_pid),
                "secs": int(secs),
                "query": query,
            }
            for pid, blocking_pid, secs, query in blocked
        ],
    }


def _query_stats(base, db_name, top, ctx=None):
    """Return the query-stats block: ``{"enabled", "stats", "stats_error"}``.

    ``stats`` holds the top queries by total time when the
    ``pg_stat_statements`` extension is created in this database, and
    ``stats_error`` marks it created but unreadable (permissions).

    ``pg_stat_statements`` >= 1.8 (PG13+) exposes ``total_exec_time``;
    older versions call it ``total_time``. The fallback handles both.
    """
    rows = store.query_or_none(
        base,
        db_name,
        "SELECT EXISTS (SELECT 1 FROM pg_extension"
        " WHERE extname = 'pg_stat_statements')",
        ctx=ctx,
    )
    result = {
        "enabled": bool(rows and rows[0][0] == "t"),
        "stats": None,
        "stats_error": False,
    }
    if not result["enabled"]:
        return result
    for total_col, mean_col in (
        ("total_exec_time", "mean_exec_time"),
        ("total_time", "mean_time"),
    ):
        rows = store.query_or_none(
            base,
            db_name,
            "SELECT left(regexp_replace(s.query, '\\s+', ' ', 'g'), 120),"
            f" s.calls, s.{total_col}::bigint, s.{mean_col}::bigint"
            " FROM pg_stat_statements s"
            " JOIN pg_database d ON d.oid = s.dbid"
            " WHERE d.datname = current_database()"
            f" ORDER BY s.{total_col} DESC LIMIT {int(top)}",
            ctx=ctx,
        )
        if rows is not None:
            result["stats"] = [
                {
                    "query": query,
                    "calls": int(calls),
                    "total_ms": int(total),
                    "mean_ms": int(mean),
                }
                for query, calls, total, mean in rows
            ]
            break
    else:
        # The extension is created but could not be read — typically a
        # permissions issue, not "no statements recorded yet".
        result["stats_error"] = True
    return result
