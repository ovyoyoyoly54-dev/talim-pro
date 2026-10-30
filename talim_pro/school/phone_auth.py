import hashlib
import hmac
import os
import re
import secrets
from urllib.parse import urlsplit

import requests
from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction
from django.utils import timezone
from datetime import timedelta

from .models import PhoneOTP, User

OTP_TTL = timedelta(minutes=10)
OTP_RESEND_WAIT = timedelta(minutes=1)
OTP_HOURLY_LIMIT = 3
OTP_MAX_ATTEMPTS = 5


def normalize_phone(value):
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 9:
        digits = "998" + digits
    elif len(digits) == 10 and digits.startswith("0"):
        digits = "998" + digits[1:]
    if not 8 <= len(digits) <= 15:
        return ""
    return "+" + digits


def _ip_digest(ip_address):
    if not ip_address:
        return ""
    return hmac.new(settings.SECRET_KEY.encode(), ip_address.encode(), hashlib.sha256).hexdigest()


def _send_code(phone, code):
    url = os.getenv("SMS_API_URL", "").strip()
    token = os.getenv("SMS_API_TOKEN", "").strip()
    if not url or not token:
        return False
    # The SMS endpoint is an outbound request configured through environment.
    # Restrict it to HTTPS hostnames and refuse redirects to prevent SSRF.
    parsed_url = urlsplit(url)
    if parsed_url.scheme != "https" or not parsed_url.hostname or parsed_url.username or parsed_url.password:
        return False
    try:
        response = requests.post(
            url,
            json={
                "to": phone,
                "message": f"TA’LIM PRO tasdiqlash kodi: {code}. Kod 10 daqiqa amal qiladi. Hech kimga bermang.",
                "sender": os.getenv("SMS_SENDER", "TalimPro"),
            },
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=12,
            allow_redirects=False,
        )
        response.raise_for_status()
        return True
    except requests.RequestException:
        # Never log the OTP, destination, token, provider URL, or provider response.
        return False


def issue_phone_otp(*, user, purpose, request):
    """Create a short-lived OTP, rate limit it, and send it without logging its body."""
    now = timezone.now()
    ip_digest = _ip_digest(request.META.get("REMOTE_ADDR", ""))
    code = f"{secrets.randbelow(1_000_000):06d}"
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user.pk)
        recent = PhoneOTP.objects.filter(user=user, purpose=purpose, created_at__gte=now - timedelta(hours=1))
        if recent.filter(created_at__gte=now - OTP_RESEND_WAIT).exists() or recent.count() >= OTP_HOURLY_LIMIT:
            return False
        if ip_digest and PhoneOTP.objects.filter(
            request_ip_digest=ip_digest, created_at__gte=now - timedelta(hours=1)
        ).count() >= OTP_HOURLY_LIMIT * 5:
            return False

        # Expired challenges are disposable; retain recent rows briefly for rate limiting.
        PhoneOTP.objects.filter(expires_at__lt=now - timedelta(days=1)).delete()
        PhoneOTP.objects.filter(user=user, purpose=purpose, consumed_at__isnull=True).update(consumed_at=now)
        challenge = PhoneOTP.objects.create(
            user=user,
            purpose=purpose,
            code_hash=make_password(code),
            request_ip_digest=ip_digest,
            expires_at=now + OTP_TTL,
        )
    if not _send_code(normalize_phone(user.phone), code):
        challenge.consumed_at = now
        challenge.save(update_fields=["consumed_at"])
        return False
    return challenge


@transaction.atomic
def consume_phone_otp(*, challenge_id, user, purpose, code):
    try:
        challenge = PhoneOTP.objects.select_for_update().get(
            pk=challenge_id, user=user, purpose=purpose, consumed_at__isnull=True
        )
    except (PhoneOTP.DoesNotExist, ValueError, TypeError):
        return False
    now = timezone.now()
    if challenge.expires_at <= now or challenge.attempts >= OTP_MAX_ATTEMPTS:
        challenge.consumed_at = now
        challenge.save(update_fields=["consumed_at"])
        return False
    if not check_password((code or "")[:6], challenge.code_hash):
        challenge.attempts += 1
        if challenge.attempts >= OTP_MAX_ATTEMPTS:
            challenge.consumed_at = now
        challenge.save(update_fields=["attempts", "consumed_at"])
        return False
    challenge.consumed_at = now
    challenge.save(update_fields=["consumed_at"])
    return True
