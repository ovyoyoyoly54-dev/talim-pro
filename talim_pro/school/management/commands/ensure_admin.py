import os

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction


class Command(BaseCommand):
    help = "Optionally create the first administrator from runtime environment secrets."

    def handle(self, *args, **options):
        username = os.getenv("DJANGO_ADMIN_USERNAME", "").strip()
        password = os.getenv("DJANGO_ADMIN_PASSWORD", "")
        email = os.getenv("DJANGO_ADMIN_EMAIL", "").strip()

        if not username and not password:
            self.stdout.write("Admin bootstrap not configured; skipping.")
            return
        if not username or not password:
            raise CommandError("DJANGO_ADMIN_USERNAME va DJANGO_ADMIN_PASSWORD ikkalasi ham sozlanishi kerak.")
        if settings.DEBUG:
            raise CommandError("Admin bootstrap faqat DEBUG=False server muhitida ishlaydi.")

        User = get_user_model()
        existing = User.objects.filter(username=username).first()
        if existing:
            if not existing.is_superuser:
                raise CommandError("Ko‘rsatilgan admin username mavjud, lekin superuser emas; administrator bilan tekshiring.")
            self.stdout.write("Administrator allaqachon mavjud; parol o‘zgartirilmadi.")
            return

        candidate = User(username=username, email=email, role=User.Role.ADMIN)
        try:
            validate_password(password, candidate)
        except ValidationError as exc:
            raise CommandError("DJANGO_ADMIN_PASSWORD parol siyosati talablariga javob bermaydi.") from exc

        try:
            with transaction.atomic():
                if User.objects.filter(username=username).exists():
                    raise IntegrityError("username already exists")
                User.objects.create_superuser(
                    username=username,
                    email=email,
                    password=password,
                    role=User.Role.ADMIN,
                )
        except IntegrityError:
            existing = User.objects.filter(username=username).first()
            if not existing or not existing.is_superuser:
                raise CommandError("Administrator yaratilolmadi; username band bo‘lishi mumkin.")
        self.stdout.write(self.style.SUCCESS("Administrator akkaunti tayyor; parolni xavfsiz saqlang."))
