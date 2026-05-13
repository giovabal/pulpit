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
