from django.apps import AppConfig


class WebappConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "webapp"
    verbose_name = "Data"

    # The WAL / synchronous pragmas formerly applied here via the
    # connection_created signal now live in DATABASES["default"]["OPTIONS"]
    # ["init_command"] (webapp_engine/settings.py), which Django runs on every
    # new connection before its first query.
