from django.apps import AppConfig


class BackofficeConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "backoffice"

    def ready(self) -> None:
        from backoffice.api.utils import register_normalize

        register_normalize()
