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
    """SQL expression: UNACCENT_LOWER(col) — accent-stripped, lowercased text."""

    function = "UNACCENT_LOWER"
    output_field = TextField()
