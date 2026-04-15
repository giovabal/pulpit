from django.apps import AppConfig


class WebappConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "webapp"
    verbose_name = "Data"

    def ready(self) -> None:
        from django.db.backends.signals import connection_created

        def _activate_wal_mode(sender, connection, **kwargs):
            # WAL mode allows concurrent reads alongside the crawler's writes,
            # dramatically reducing "database is locked" errors under SQLite.
            # journal_mode is a per-file setting; it only takes effect the first
            # time it is set on a connection and persists in the DB file.
            if connection.vendor == "sqlite":
                with connection.cursor() as cursor:
                    cursor.execute("PRAGMA journal_mode=WAL;")
                    cursor.execute("PRAGMA synchronous=NORMAL;")

        connection_created.connect(_activate_wal_mode)
