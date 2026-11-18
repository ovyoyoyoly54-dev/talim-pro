"""Administratorlar uchun 2 bosqichli tasdiqlash (TOTP) va uni majburlovchi middleware."""
import base64
import hashlib
import hmac
import io
import secrets
import time

import pyotp
from django.conf import settings
from django.core.cache import cache
from django.shortcuts import redirect
from django.urls import reverse

from .models import TwoFactorDevice, User

ISSUER = "TA'LIM PRO"
MAX_ATTEMPTS = 5
LOCK_SECONDS = 600
SESSION_KEY = "2fa_ok"


def is_enforced(user):
    """Administrator uchun 2FA majburiymi (faqat ADMIN_2FA_REQUIRED=True bo'lganda)."""
    return bool(
        settings.ADMIN_2FA_REQUIRED and user.is_authenticated
        and (user.is_superuser or user.is_staff or user.role == User.Role.ADMIN)
    )


def is_enrolled(user):
    """Foydalanuvchi 2FA ni ixtiyoriy yoqqan (tasdiqlangan qurilmasi bor)."""
    return bool(user.is_authenticated and TwoFactorDevice.objects.filter(user=user, confirmed=True).exists())


def requires_two_factor(user):
    return is_enforced(user) or is_enrolled(user)


def new_secret():
    return pyotp.random_base32()


def provisioning_uri(user, secret):
    return pyotp.TOTP(secret).provisioning_uri(name=user.get_username(), issuer_name=ISSUER)


def qr_data_uri(uri):
    import qrcode
    image = qrcode.make(uri, box_size=6, border=2)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


def check_totp(secret, code, last_counter=0):
    """Kod to‘g‘ri bo‘lsa — foydalanilgan vaqt oynasi raqamini, aks holda None qaytaradi.

    Bir xil kod ikki marta qabul qilinmaydi (replay himoyasi).
    """
    code = (code or "").strip().replace(" ", "")
    if not (code.isdigit() and len(code) == 6):
        return None
    totp = pyotp.TOTP(secret)
    now = int(time.time() // totp.interval)
    for counter in (now, now - 1, now + 1):
        if counter > last_counter and hmac.compare_digest(totp.at(counter * totp.interval), code):
            return counter
    return None


def _hash_backup(code):
    normalized = code.strip().lower().replace("-", "")
    return hmac.new(settings.SECRET_KEY.encode(), normalized.encode(), hashlib.sha256).hexdigest()


def make_backup_codes(count=8):
    codes = [f"{secrets.token_hex(3)}-{secrets.token_hex(3)}" for _ in range(count)]
    return codes, [_hash_backup(c) for c in codes]


def use_backup_code(device, code):
    digest = _hash_backup(code or "")
    for stored in device.backup_code_hashes:
        if hmac.compare_digest(stored, digest):
            device.backup_code_hashes = [h for h in device.backup_code_hashes if h != stored]
            device.save(update_fields=["backup_code_hashes"])
            return True
    return False


def _attempt_key(user):
    return f"2fa-attempts:{user.pk}"


def is_locked(user):
    return cache.get(_attempt_key(user), 0) >= MAX_ATTEMPTS


def register_failure(user):
    key = _attempt_key(user)
    cache.set(key, cache.get(key, 0) + 1, LOCK_SECONDS)


def clear_failures(user):
    cache.delete(_attempt_key(user))


EXEMPT_PREFIXES = ("/2fa/", "/logout/", "/static/", "/service-worker.js", "/manifest.webmanifest", "/offline/")


class TwoFactorMiddleware:
    """Parol bilan kirgan administratorni 2FA tasdiqlanmaguncha faqat 2FA sahifalariga o‘tkazadi."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if (
            user is not None and user.is_authenticated
            and not request.session.get(SESSION_KEY)
            and not request.path.startswith(EXEMPT_PREFIXES)
            and requires_two_factor(user)
        ):
            device = TwoFactorDevice.objects.filter(user=user, confirmed=True).first()
            target = reverse("two_factor_verify" if device else "two_factor_setup")
            nxt = request.get_full_path() if request.method == "GET" else ""
            return redirect(f"{target}?next={nxt}" if nxt else target)
        return self.get_response(request)


class AuditMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from . import audit
        audit.set_context(request)
        try:
            return self.get_response(request)
        finally:
            audit.clear_context()
