import asyncio
from typing import Any

from django.core.management.base import BaseCommand


class AsyncBaseCommand(BaseCommand):
    def execute(self, *args: Any, **options: Any) -> Any:
        try:
            asyncio.get_running_loop()
            return super().execute(*args, **options)
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return super().execute(*args, **options)
            finally:
                loop.close()
