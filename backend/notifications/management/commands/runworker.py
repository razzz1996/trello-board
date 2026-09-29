from __future__ import annotations

import time

from django.conf import settings
from django.core.management.base import BaseCommand

from notifications.worker import worker_tick


class Command(BaseCommand):
    help = "Run the durable productivity job worker."

    def handle(self, *args, **options):
        delay = int(settings.DEPLOYMENT["worker_tick_seconds"])
        self.stdout.write("Worker started; Slack mode=" + settings.DEPLOYMENT["slack_mode"])
        try:
            while True:
                worker_tick()
                time.sleep(delay)
        except KeyboardInterrupt:
            self.stdout.write("Worker stopped.")
