import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from django.core.management.base import BaseCommand


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class Command(BaseCommand):
    help = "Web Push uchun VAPID kalit juftligini yaratadi (.env ga qo‘shing)."

    def handle(self, *args, **options):
        key = ec.generate_private_key(ec.SECP256R1())
        private = _b64(key.private_numbers().private_value.to_bytes(32, "big"))
        public = _b64(key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))
        self.stdout.write(f"VAPID_PUBLIC_KEY={public}")
        self.stdout.write(f"VAPID_PRIVATE_KEY={private}")
        self.stdout.write(self.style.WARNING("Maxfiy kalitni hech kimga bermang va git'ga qo‘shmang."))
