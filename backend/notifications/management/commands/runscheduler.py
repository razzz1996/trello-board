from __future__ import annotations

import time

from django.conf import settings
from django.core.management.base import BaseCommand

from notifications.scheduler import scheduler_tick


class Command(BaseCommand):
    help = "Run the productivity scheduler loop."

    def handle(self, *args, **options):
        delay = int(settings.DEPLOYMENT["worker_tick_seconds"])
        self.stdout.write("Scheduler started.")
        try:
            while True:
                scheduler_tick()
                time.sleep(delay)
        except KeyboardInterrupt:
            self.stdout.write("Scheduler stopped.")
