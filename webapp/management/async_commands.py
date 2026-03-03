import asyncio

from django.core.management.base import BaseCommand


class AsyncBaseCommand(BaseCommand):
    def _ensure_event_loop(self) -> None:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.set_event_loop(asyncio.new_event_loop())
