import os
from urllib.parse import urlsplit

import requests

from .models import SMSLog


def send_parent_sms(*, parent=None, student, body, phone=None):
    """Send an SMS through the configured HTTPS JSON gateway."""
    url = os.getenv("SMS_API_URL", "").strip()
    token = os.getenv("SMS_API_TOKEN", "").strip()
    phone = (phone or (parent.phone if parent else "")).strip()

    parsed_url = urlsplit(url) if url else None
    valid_url = bool(
        parsed_url
        and parsed_url.scheme == "https"
        and parsed_url.hostname
        and not parsed_url.username
        and not parsed_url.password
    )
    if not valid_url or not token or not phone:
        return SMSLog.objects.create(
            parent=parent,
            student=student,
            body=body,
            status=SMSLog.Status.DISABLED,
            provider_response="SMS sozlanmagan yoki HTTPS manzili noto‘g‘ri.",
        )

    try:
        response = requests.post(
            url,
            json={
                "to": phone,
                "message": body,
                "sender": os.getenv("SMS_SENDER", "TalimPro"),
            },
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=12,
            allow_redirects=False,
        )
        # Redirects are not successful sends; never follow a gateway redirect.
        if not 200 <= response.status_code < 300:
            return SMSLog.objects.create(
                parent=parent,
                student=student,
                body=body,
                status=SMSLog.Status.FAILED,
                provider_response=f"HTTP {response.status_code}",
            )
        return SMSLog.objects.create(
            parent=parent,
            student=student,
            body=body,
            status=SMSLog.Status.SENT,
            provider_response=f"HTTP {response.status_code}",
        )
    except requests.RequestException as exc:
        response = getattr(exc, "response", None)
        provider_response = (
            f"HTTP {response.status_code}"
            if response is not None
            else f"Ulanish xatosi: {type(exc).__name__}"
        )
        return SMSLog.objects.create(
            parent=parent,
            student=student,
            body=body,
            status=SMSLog.Status.FAILED,
            provider_response=provider_response,
        )
