import unicodedata

from django.db.backends.signals import connection_created
from django.db.models import Func, TextField


def _normalize(s: str) -> str:
    """Strip accents/diacritics and lowercase. 'Hélix' → 'helix', 'ç' → 'c'."""
    if not s:
        return ""
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


def _sqlite_handler(sender, connection, **kwargs) -> None:
    if connection.vendor == "sqlite":
        connection.connection.create_function("UNACCENT_LOWER", 1, _normalize)


def register_normalize() -> None:
    """Connect the signal and register on any already-open SQLite connection."""
    connection_created.connect(_sqlite_handler)
    from django.db import connection

    if connection.vendor == "sqlite" and connection.connection is not None:
        connection.connection.create_function("UNACCENT_LOWER", 1, _normalize)


class UnaccentLower(Func):
    """SQL expression: UNACCENT_LOWER(col) — accent-stripped, lowercased text.

    Only SQLite has the registered ``UNACCENT_LOWER`` UDF. The other engines
    settings.py supports (PostgreSQL, MySQL/MariaDB, Oracle) have no portable
    equivalent (PostgreSQL would need the ``unaccent`` extension), so they all fall
    back to ``LOWER`` — channel search stays case-insensitive (accent-sensitive)
    instead of raising ``function unaccent_lower(...) does not exist``. Pair with
    :func:`normalize_for_search` so the query term matches the column transform.
    """

    function = "UNACCENT_LOWER"
    output_field = TextField()

    def _as_lower(self, compiler, connection, **extra_context):
        return super().as_sql(compiler, connection, function="LOWER", **extra_context)

    as_postgresql = _as_lower
    as_mysql = _as_lower  # MariaDB uses the mysql vendor too
    as_oracle = _as_lower


def normalize_for_search(text: str) -> str:
    """Normalize a search term to match what :class:`UnaccentLower` renders on the
    active backend: accent-stripped + lowercased on SQLite (the UNACCENT_LOWER UDF),
    lowercased-only on PostgreSQL (which falls back to LOWER)."""
    from django.db import connection

    if connection.vendor == "sqlite":
        return _normalize(text)
    return (text or "").lower()
