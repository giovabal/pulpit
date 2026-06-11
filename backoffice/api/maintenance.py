"""Database maintenance: vacuum, analyze, and other engine-specific optimizations."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from django.db import connection

from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

_STRATEGIES: dict[str, list[dict[str, str]]] = {
    "sqlite": [
        {
            "name": "analyze",
            "label": "ANALYZE",
            "description": (
                "Refreshes the statistics SQLite uses to plan queries. Inexpensive (seconds), "
                "no exclusive lock; safe to run any time."
            ),
        },
        {
            "name": "optimize",
            "label": "PRAGMA optimize",
            "description": (
                "Runs SQLite's recommended periodic maintenance. Re-analyzes only the tables "
                "whose statistics look stale. Fast and safe."
            ),
        },
        {
            "name": "checkpoint",
            "label": "WAL checkpoint (TRUNCATE)",
            "description": (
                "Flushes the write-ahead log into the main database file and shrinks the WAL "
                "file back to zero. Reclaims disk space used by the journal."
            ),
        },
        {
            "name": "vacuum",
            "label": "VACUUM",
            "description": (
                "Rebuilds the database file from scratch, compacting free pages and "
                "defragmenting storage. Takes minutes on a multi-GB database and holds an "
                "exclusive lock — other requests will queue while it runs."
            ),
        },
    ],
    "postgresql": [
        {
            "name": "analyze",
            "label": "ANALYZE",
            "description": "Updates planner statistics. Cheap; safe to run any time.",
        },
        {
            "name": "vacuum",
            "label": "VACUUM ANALYZE",
            "description": (
                "Reclaims storage from dead rows and updates statistics in one pass. Does not "
                "hold an exclusive lock and is safe alongside live traffic."
            ),
        },
    ],
}


def _db_size_bytes() -> int | None:
    if connection.vendor == "sqlite":
        path = Path(connection.settings_dict["NAME"])
        return path.stat().st_size if path.exists() else None
    if connection.vendor == "postgresql":
        with connection.cursor() as cur:
            cur.execute("SELECT pg_database_size(current_database())")
            return int(cur.fetchone()[0])
    return None


_SQLITE_SQL = {
    "analyze": "ANALYZE",
    "optimize": "PRAGMA optimize",
    "checkpoint": "PRAGMA wal_checkpoint(TRUNCATE)",
    "vacuum": "VACUUM",
}

_POSTGRES_SQL = {
    "analyze": "ANALYZE",
    "vacuum": "VACUUM ANALYZE",
}


def _run(name: str) -> None:
    if connection.vendor == "sqlite":
        sql = _SQLITE_SQL[name]
        with connection.cursor() as cur:
            cur.execute(sql)
            if name == "checkpoint":
                # PRAGMA wal_checkpoint never raises on contention — it returns a
                # (busy, log, checkpointed) row, busy=1 meaning the WAL could not be
                # checkpointed/truncated (e.g. a concurrent reader holds a snapshot).
                # Reporting that as "ok" would tell the operator space was reclaimed
                # when nothing happened.
                row = cur.fetchone()
                if row and row[0]:
                    raise RuntimeError(
                        "WAL checkpoint could not complete: the database is busy "
                        "(another connection holds a read snapshot). Retry when the "
                        "crawler/analysis is idle."
                    )
        return
    if connection.vendor == "postgresql":
        sql = _POSTGRES_SQL[name]
        was_autocommit = connection.get_autocommit()
        connection.set_autocommit(True)
        try:
            with connection.cursor() as cur:
                cur.execute(sql)
        finally:
            connection.set_autocommit(was_autocommit)
        return
    raise RuntimeError(f"Unsupported engine: {connection.vendor}")


@api_view(["GET"])
def maintenance_info(request: Any) -> Response:
    engine = connection.vendor
    return Response(
        {
            "engine": engine,
            "supported": engine in _STRATEGIES,
            "size_bytes": _db_size_bytes(),
            "strategies": _STRATEGIES.get(engine, []),
        }
    )


@api_view(["GET"])
def purge_preview(request: Any) -> Response:
    """Count messages and media files that would be deleted by a purge run.

    Mirrors ``manage.py purge_out_of_target_messages --dry-run`` but as a
    JSON endpoint so the Maintenance page can show the impact before the
    analyst commits.
    """
    from webapp.management.commands.purge_out_of_target_messages import marked_in_target_channels, purge

    marked_count = marked_in_target_channels().count()
    if marked_count == 0:
        return Response(
            {
                "marked_in_target_channels": 0,
                "messages": 0,
                "media_files": 0,
                "supported": False,
                "detail": (
                    "No channels are marked in-target. Mark at least one channel or organisation "
                    "before previewing — a purge with no in-target scope would delete every message."
                ),
            }
        )
    report = purge(dry_run=True)
    return Response(
        {
            "marked_in_target_channels": marked_count,
            "messages": report.candidate_messages,
            "media_files": report.candidate_media_files,
            "supported": True,
        }
    )


@api_view(["GET"])
def orphan_media_preview(request: Any) -> Response:
    """Count files under media scan roots with no row reference, and their total size."""
    from webapp.management.commands.purge_orphan_media import purge_orphans, scan_roots

    existing = [r for r in scan_roots() if r.is_dir()]
    if not existing:
        return Response(
            {
                "files": 0,
                "bytes": 0,
                "supported": False,
                "detail": "No media scan roots exist on disk — nothing to scan.",
            }
        )
    report = purge_orphans(dry_run=True)
    return Response(
        {
            "files": report.candidate_files,
            "bytes": report.candidate_bytes,
            "supported": True,
        }
    )


@api_view(["POST"])
def orphan_media_run(request: Any) -> Response:
    """Delete orphan media files from disk; tidy up the empty directories left behind."""
    from webapp.management.commands.purge_orphan_media import purge_orphans, scan_roots

    existing = [r for r in scan_roots() if r.is_dir()]
    if not existing:
        return Response(
            {"detail": "No media scan roots exist on disk — nothing to scan."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    overall_t = time.perf_counter()
    report = purge_orphans(dry_run=False)
    return Response(
        {
            "candidate_files": report.candidate_files,
            "candidate_bytes": report.candidate_bytes,
            "removed_files": report.removed_files,
            "removed_bytes": report.removed_bytes,
            "failed_files": report.failed_files,
            "empty_dirs_removed": report.empty_dirs_removed,
            "total_duration_seconds": time.perf_counter() - overall_t,
        }
    )


@api_view(["POST"])
def purge_run(request: Any) -> Response:
    """Delete messages (and on-disk media) for channels outside the in-target scope.

    Backs the "Purge out-of-target messages" button on the Maintenance page.
    Refuses to run when no channel is marked in-target (would otherwise nuke
    the entire message table).
    """
    from django.core.management.base import CommandError

    from webapp.management.commands.purge_out_of_target_messages import purge

    size_before = _db_size_bytes()
    overall_t = time.perf_counter()
    try:
        report = purge(dry_run=False)
    except CommandError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(
        {
            "candidate_messages": report.candidate_messages,
            "candidate_media_files": report.candidate_media_files,
            "deleted_messages": report.deleted_messages,
            "removed_files": report.removed_files,
            "failed_files": report.failed_files,
            "size_before_bytes": size_before,
            "size_after_bytes": _db_size_bytes(),
            "total_duration_seconds": time.perf_counter() - overall_t,
        }
    )


@api_view(["POST"])
def check_updates(request: Any) -> Response:
    """Force a fresh upstream version check, bypassing the once-a-day cache.

    Backs the "Check for updates" button on the Maintenance page. The attention
    dots and banner across the UI read a day-cached lookup; this refetches the
    upstream ``.system`` from GitHub right now and refreshes that shared cache.
    Fails open like the rest of :mod:`webapp.version_check`: a network error or a
    non-GitHub repository yields ``latest: null`` rather than an error response.
    """
    from webapp.version_check import version_status

    return Response(version_status(force_refresh=True))


@api_view(["POST"])
def maintenance_optimize(request: Any) -> Response:
    engine = connection.vendor
    if engine not in _STRATEGIES:
        return Response(
            {"detail": f"Database engine {engine!r} is not supported for maintenance."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    catalog = _STRATEGIES[engine]
    all_names = [s["name"] for s in catalog]
    requested = request.data.get("strategies") or all_names
    invalid = [n for n in requested if n not in all_names]
    if invalid:
        return Response(
            {"detail": f"Unknown strategies for {engine}: {', '.join(invalid)}"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    selected = [n for n in all_names if n in requested]

    size_before = _db_size_bytes()
    overall_t = time.perf_counter()
    steps: list[dict[str, Any]] = []
    for name in selected:
        t = time.perf_counter()
        try:
            _run(name)
            steps.append({"name": name, "status": "ok", "duration_seconds": time.perf_counter() - t})
        except Exception as exc:
            steps.append(
                {
                    "name": name,
                    "status": "error",
                    "duration_seconds": time.perf_counter() - t,
                    "error": str(exc),
                }
            )
            break
    return Response(
        {
            "engine": engine,
            "size_before_bytes": size_before,
            "size_after_bytes": _db_size_bytes(),
            "total_duration_seconds": time.perf_counter() - overall_t,
            "steps": steps,
        }
    )
