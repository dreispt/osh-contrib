"""Render the ``osh db stats`` report as a text dashboard.

Zero-dependency: section rules, aligned columns and proportional block
bars are drawn by hand, and severity colors go through ``click.style``
(which strips ANSI codes automatically when the output is not a TTY).
"""

import shutil

import click

MAX_WIDTH = 100
BAR_WIDTH = 16


def dashboard(report, *, width=None):
    """Return the full dashboard text for a :func:`report.collect` result."""
    width = min(width or shutil.get_terminal_size().columns, MAX_WIDTH)
    lines = []
    lines += _overview_section(report, width)
    lines += _largest_tables_section(report, width)
    lines += _health_section(report, width)
    lines += _indexes_section(report, width)
    lines += _activity_section(report, width)
    lines += _query_stats_section(report, width)
    lines += _summary(report)
    return "\n".join(lines)


def _overview_section(report, width):
    ov = report["overview"]
    lines = [_rule(f"DATABASE  {report['db_name']}", width)]
    size_parts = [_size(ov["size_bytes"])]
    filestore = report.get("filestore")
    if filestore and filestore["bytes"] is not None:
        size_parts.append(f"+ {_size(filestore['bytes'])} filestore")
    stats_age = (
        f"stats reset {_age(ov['stats_age_secs'])} ago"
        if ov["stats_age_secs"]
        else "no stats yet"
    )
    lines.append(
        f"{' '.join(size_parts)} · {ov['table_count']} tables · "
        f"{_count(ov['row_count'])} rows · {stats_age}"
    )
    server = f"PostgreSQL {ov['server_version']}"
    if report.get("odoo_version"):
        server += f" · Odoo {report['odoo_version']}"
    else:
        server += " · not an Odoo database"
    lines.append(server)
    if filestore and filestore["bytes"] is None:
        if filestore["path"]:
            lines.append(f"filestore: not found ({filestore['path']})")
        else:
            lines.append("filestore: Odoo data dir not found")
    return lines + [""]


def _largest_tables_section(report, width):
    tables = report["largest_tables"]
    if not tables:
        return [_rule("LARGEST TABLES", width), "no user tables", ""]
    top = tables[0]["total_bytes"] or 1
    name_w = max(len(t["name"]) for t in tables)
    lines = [_rule("LARGEST TABLES", width)]
    for t in tables:
        lines.append(
            f"{t['name']:<{name_w}}  {_size(t['total_bytes']):>8}  "
            f"{_bar(t['total_bytes'] / top)}  "
            f"{_size(t['table_bytes'])} data · {_size(t['index_bytes'])} idx · "
            f"{_count(t['rows'])} rows"
        )
    return lines + [""]


def _health_section(report, width):
    bloated = report["bloated_tables"]
    if not bloated:
        return [_rule("TABLE HEALTH", width), "no tables need vacuum", ""]
    name_w = max(len(t["name"]) for t in bloated)
    lines = [_rule("TABLE HEALTH", width)]
    for t in bloated:
        dead = f"{t['ratio'] * 100:.0f}% dead ({_count(t['dead'])})"
        vacuum = (
            f"vacuumed {_age(t['vacuum_age_secs'])} ago"
            if t["vacuum_age_secs"] is not None
            else "never vacuumed"
        )
        analyze = (
            f"analyzed {_age(t['analyze_age_secs'])} ago"
            if t["analyze_age_secs"] is not None
            else "never analyzed"
        )
        fg = "red" if t["ratio"] >= 0.30 else "yellow"
        lines.append(
            click.style(f"{t['name']:<{name_w}}", fg=fg, bold=True)
            + click.style(f"  {dead:<20} · {vacuum} · {analyze}", fg=fg)
        )
    return lines + [""]


def _indexes_section(report, width):
    largest = report["indexes"]["largest"]
    if not largest:
        return [_rule("INDEXES", width), "no user indexes", ""]
    indexes = report["indexes"]
    name_w = max(len(i["name"]) for i in largest)
    lines = [
        _rule("INDEXES", width),
        f"{_size(indexes['total_bytes'])} across {indexes['count']} indexes",
    ]
    for i in largest:
        lines.append(
            f"{i['name']:<{name_w}}  {_size(i['bytes']):>8}  {i['table']} · "
            f"{_count(i['scans'])} scans"
        )
    return lines + [""]


def _activity_section(report, width):
    act = report["activity"]
    lines = [_rule("ACTIVITY", width)]
    if act["connections"] is None:
        return lines + ["activity unavailable on this server", ""]
    states = " · ".join(f"{state} {count}" for state, count in act["states"].items())
    ratio = act["connections"] / act["max_connections"]
    fg = "red" if ratio > 0.8 else "yellow" if ratio > 0.6 else None
    lines.append(
        click.style(
            f"connections: {act['connections']}/{act['max_connections']} ({states})",
            fg=fg,
        )
    )
    if act["autovacuum_workers"]:
        lines.append(f"autovacuum workers: {act['autovacuum_workers']} running")
    if act["long_running"]:
        lines.append(click.style("long-running queries:", fg="red"))
        for q in act["long_running"]:
            lines.append(f"  pid {q['pid']} · {_age(q['secs'])} · {q['query']}")
    if act["blocked"]:
        lines.append(click.style("blocked queries:", fg="red"))
        for q in act["blocked"]:
            lines.append(
                f"  pid {q['pid']} blocked by {q['blocking_pid']} · "
                f"{_age(q['secs'])} · {q['query']}"
            )
    if not act["long_running"] and not act["blocked"]:
        lines.append("no long-running or blocked queries")
    return lines + [""]


def _query_stats_section(report, width):
    stats = report["query_stats"]
    lines = [_rule("QUERY STATS", width)]
    if stats["enabled"]:
        if stats["stats_error"]:
            lines.append(
                "pg_stat_statements is enabled but could not be read "
                "— check permissions"
            )
        elif not stats["stats"]:
            lines.append("pg_stat_statements enabled, no statements recorded yet")
        else:
            for q in stats["stats"]:
                lines.append(
                    f"{_count(q['calls']):>6} calls · {_ms(q['total_ms']):>8} total · "
                    f"{_ms(q['mean_ms']):>7} avg · {q['query']}"
                )
    else:
        lines.append(
            "pg_stat_statements is not enabled — live activity shown above; "
            "see 'osh db stats --help' to enable it."
        )
    return lines + [""]


def _summary(report):
    """Return a one-line footer aggregating the flagged issues."""
    issues = []
    bloated = report["bloated_tables"]
    if bloated:
        issues.append(f"{len(bloated)} bloated table(s) — see 'osh db vacuum'")
    act = report["activity"]
    if act["long_running"] or act["blocked"]:
        issues.append(
            f"{len(act['long_running']) + len(act['blocked'])} query problem(s)"
        )
    if not issues:
        return [click.style("✓ no issues found", fg="green")]
    return [click.style("⚠ " + " · ".join(issues), fg="yellow", bold=True)]


def _rule(title, width):
    """Return ``── TITLE ────...`` padded to *width*."""
    head = f"{title} "
    return click.style(head + "─" * max(width - len(head), 0), fg="cyan", bold=True)


def _bar(frac, width=BAR_WIDTH):
    """Return a proportional ``████░░`` bar."""
    fill = round(max(0.0, min(frac, 1.0)) * width)
    return "█" * fill + "░" * (width - fill)


def _size(nbytes):
    """Format a byte count as ``800 MB`` / ``4.2 GB``."""
    value = float(nbytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "B":
                return f"{value:.0f} {unit}"
            return f"{value:.1f} {unit}" if value < 10 else f"{value:.0f} {unit}"
        value /= 1024
    return f"{value:.0f} TB"


def _count(n):
    """Format an estimate as ``~4.1M`` / ``~950k`` / ``42``."""
    if n >= 1_000_000:
        return f"~{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"~{n / 1_000:.0f}k"
    return str(n)


def _age(secs):
    """Format an age in seconds as ``12d`` / ``3h`` / ``45m`` / ``now``."""
    if secs < 60:
        return "now"
    if secs < 3600:
        return f"{secs // 60}m"
    if secs < 86400:
        return f"{secs // 3600}h"
    return f"{secs // 86400}d"


def _ms(milliseconds):
    """Format a duration in ms as ``68ms`` / ``1.2s`` / ``45s``."""
    if milliseconds < 1000:
        return f"{milliseconds}ms"
    return (
        f"{milliseconds / 1000:.1f}s"
        if milliseconds < 10_000
        else f"{milliseconds // 1000}s"
    )
