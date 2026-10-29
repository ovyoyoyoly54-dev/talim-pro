import os
import requests
from .models import SMSLog

def send_parent_sms(*, parent, student, body):
    """Generic JSON SMS gateway adapter. Configure SMS_API_URL and SMS_API_TOKEN in .env.
    Provider-specific payload/auth can be adapted in this one function.
    """
    url = os.getenv("SMS_API_URL", "").strip()
    token = os.getenv("SMS_API_TOKEN", "").strip()
    phone = (parent.phone if parent else "").strip()
    if not url or not token or not phone:
        return SMSLog.objects.create(
            parent=parent, student=student, body=body,
            status=SMSLog.Status.DISABLED,
            provider_response="SMS sozlanmagan yoki ota-onaning telefon raqami yo‘q."
        )
    try:
        response = requests.post(
            url,
            json={"to": phone, "message": body, "sender": os.getenv("SMS_SENDER", "TalimPro")},
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=12,
        )
        response.raise_for_status()
        return SMSLog.objects.create(parent=parent, student=student, body=body,
                                     status=SMSLog.Status.SENT, provider_response=response.text[:2000])
    except requests.RequestException as exc:
        return SMSLog.objects.create(parent=parent, student=student, body=body,
                                     status=SMSLog.Status.FAILED, provider_response=str(exc)[:2000])
