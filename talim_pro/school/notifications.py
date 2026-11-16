"""Bildirishnomalar: ilova ichidagi xabar + Web Push; kerak bo‘lsa SMS zaxirasi."""
import json
import logging

from django.conf import settings
from django.utils.translation import gettext as _

from .models import Notification, PushSubscription, SMSLog

logger = logging.getLogger(__name__)


def push_enabled():
    return bool(settings.VAPID_PUBLIC_KEY and settings.VAPID_PRIVATE_KEY)


def _send_push(subscription, payload):
    if not push_enabled():
        return False
    try:
        from pywebpush import WebPushException, webpush
    except ImportError:  # pragma: no cover
        return False
    try:
        webpush(
            subscription_info={"endpoint": subscription.endpoint,
                               "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth}},
            data=json.dumps(payload),
            vapid_private_key=settings.VAPID_PRIVATE_KEY,
            vapid_claims={"sub": f"mailto:{settings.VAPID_CLAIM_EMAIL}"},
            ttl=86400, timeout=8,
        )
        return True
    except WebPushException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status in (404, 410):  # obuna eskirgan
            subscription.delete()
        else:
            logger.warning("Push yuborilmadi: %s", type(exc).__name__)
    except Exception as exc:  # noqa: BLE001 — push xatosi asosiy jarayonni to‘xtatmasligi kerak
        logger.warning("Push xatosi: %s", type(exc).__name__)
    return False


def notify(users, title, body="", url=""):
    """Foydalanuvchilarga xabar yaratadi va push yuboradi. Push olgan foydalanuvchilar sonini qaytaradi."""
    users = {u.pk: u for u in users if u is not None and u.is_active}
    pushed = 0
    for user in users.values():
        Notification.objects.create(user=user, title=title[:120], body=body[:400], url=url[:200])
        delivered = False
        for sub in list(user.push_subscriptions.all()):
            delivered = _send_push(sub, {"title": title, "body": body, "url": url or "/"}) or delivered
        pushed += int(delivered)
    return pushed


def family_users(student):
    return [student.user, student.parent]


def has_push(users):
    return any(u and u.push_subscriptions.exists() for u in users) and push_enabled()


def notify_family(student, title, body, url="", *, sms_body=None):
    """O‘quvchi va ota-onasiga xabar yuboradi.

    Push yetib borishi mumkin bo‘lsa SMS yuborilmaydi (SMS xarajatini tejash); aks holda,
    ota-ona raqami bor bo‘lsa va `sms_body` berilgan bo‘lsa, SMS zaxira kanal bo‘ladi.
    """
    users = family_users(student)
    pushed = has_push(users)
    notify(users, title, body, url)
    if sms_body and not pushed and student.parent_phone:
        from .sms import send_parent_sms
        log = send_parent_sms(parent=None, student=student, phone=student.parent_phone, body=sms_body)
        return log.status == SMSLog.Status.SENT
    return pushed


def notify_invoice_created(invoices):
    for invoice in invoices:
        notify_family(
            invoice.student, _("Yangi to‘lov hisobi"),
            _("%(month)s oyi uchun %(amount)s so‘m. Muddat: %(due)s.") % {
                "month": invoice.period.strftime("%m.%Y"), "amount": f"{invoice.amount:.0f}",
                "due": invoice.due_date.strftime("%d.%m.%Y")},
            "/tolovlar/",
        )


def notify_payment_received(payment):
    notify_family(
        payment.invoice.student, _("To‘lov qabul qilindi"),
        _("%(amount)s so‘m to‘lov qabul qilindi. Rahmat!") % {"amount": f"{payment.amount:.0f}"},
        "/tolovlar/",
    )


def notify_debt_reminder(rows):
    sent = 0
    for row in rows:
        student = row["student"]
        text = _("Muddati o‘tgan qarz: %(debt)s so‘m. Iltimos, to‘lovni amalga oshiring.") % {"debt": f"{row['debt']:.0f}"}
        notify_family(student, _("To‘lov eslatmasi"), text, "/tolovlar/",
                      sms_body=f"TA'LIM PRO: {student.user.get_full_name() or student.user.username}. {text}")
        sent += 1
    return sent
