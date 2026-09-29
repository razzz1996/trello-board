from __future__ import annotations

import getpass

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

User = get_user_model()


class Command(BaseCommand):
    help = "Create the first local administrator using a hidden interactive password prompt."

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)

    def handle(self, *args, **options):
        username = str(options["username"]).strip()
        if not username or len(username) > 150:
            raise CommandError("Username is required and must be at most 150 characters.")
        if User.objects.filter(is_active=True).filter(
            is_staff=True
        ).exists():
            raise CommandError(
                "An active administrator already exists. Use the audited admin UI for further accounts."
            )
        if User.objects.filter(username__iexact=username).exists():
            raise CommandError("That username is already in use.")

        candidate = User(username=username, is_staff=True, is_active=True)
        first = getpass.getpass("New administrator password: ")
        second = getpass.getpass("Confirm administrator password: ")
        if first != second:
            raise CommandError("Passwords do not match.")
        try:
            validate_password(first, user=candidate)
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from exc

        with transaction.atomic():
            if User.objects.select_for_update().filter(
                is_active=True, is_staff=True
            ).exists():
                raise CommandError("Another administrator was created concurrently.")
            candidate.set_password(first)
            candidate.force_password_change = False
            candidate.save()
        self.stdout.write(self.style.SUCCESS(f"Administrator '{username}' created."))
