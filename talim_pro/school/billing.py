"""To‘lov hisoblarini yaratish va qarzdorlik hisob-kitobi."""
import base64
from datetime import date
from decimal import Decimal
from urllib.parse import urlencode

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Sum
from django.utils import timezone

from .models import Invoice, Payment, StudentProfile, User


def first_of_month(day=None):
    day = day or timezone.localdate()
    return day.replace(day=1)


def parse_period(value):
    """'2026-11' yoki '2026-11-05' ko‘rinishini oyning 1-sanasiga aylantiradi."""
    try:
        parts = str(value).split("-")
        return date(int(parts[0]), int(parts[1]), 1)
    except (ValueError, IndexError, TypeError):
        return None


def generate_invoices(period, *, due_day=None, group=None):
    """Faol o‘quvchilar uchun oylik hisoblarni yaratadi (mavjudlari qayta yaratilmaydi).

    Guruh narxi 0 bo‘lsa, hisob yaratilmaydi. Natija: (yaratilganlar ro‘yxati, o‘tkazib yuborilganlar soni).
    """
    due_day = due_day or getattr(settings, "INVOICE_DUE_DAY", 10)
    due_day = max(1, min(int(due_day), 28))
    due_date = period.replace(day=due_day)
    profiles = StudentProfile.objects.filter(
        user__role=User.Role.STUDENT, user__is_active=True, group__monthly_fee__gt=0,
    ).select_related("group", "user")
    if group is not None:
        profiles = profiles.filter(group=group)
    skipped = 0
    new_invoices = []
    with transaction.atomic():
        existing = set(Invoice.objects.filter(period=period).values_list("student_id", flat=True))
        for profile in profiles:
            if profile.pk in existing:
                skipped += 1
                continue
            new_invoices.append(Invoice(
                student=profile, period=period, amount=profile.group.monthly_fee, due_date=due_date,
            ))
        new_invoices = Invoice.objects.bulk_create(new_invoices)
    return new_invoices, skipped


def debtors(today=None):
    """Muddati o‘tgan va to‘liq to‘lanmagan hisoblar bo‘yicha o‘quvchilar ro‘yxati."""
    today = today or timezone.localdate()
    rows = {}
    invoices = Invoice.objects.exclude(status__in=[Invoice.Status.PAID, Invoice.Status.CANCELLED]).filter(
        due_date__lt=today,
    ).select_related("student__user", "student__group")
    for invoice in invoices:
        balance = invoice.balance
        if balance <= 0:
            continue
        row = rows.setdefault(invoice.student_id, {
            "student": invoice.student, "debt": Decimal("0"), "invoices": 0, "oldest": invoice.due_date,
        })
        row["debt"] += balance
        row["invoices"] += 1
        row["oldest"] = min(row["oldest"], invoice.due_date)
    return sorted(rows.values(), key=lambda r: (-r["debt"], r["student"].user.last_name))


def month_summary(period):
    invoices = Invoice.objects.filter(period=period).exclude(status=Invoice.Status.CANCELLED)
    billed = invoices.aggregate(v=Sum("amount"))["v"] or Decimal("0")
    paid = Payment.objects.filter(
        invoice__in=invoices, status=Payment.Status.COMPLETED,
    ).aggregate(v=Sum("amount"))["v"] or Decimal("0")
    return {"billed": billed, "paid": paid, "left": max(billed - paid, Decimal("0")),
            "count": invoices.aggregate(c=Count("id"))["c"]}


def to_tiyin(amount):
    return int((Decimal(amount) * 100).to_integral_value())


def click_pay_url(invoice, request=None):
    service_id = getattr(settings, "CLICK_SERVICE_ID", "")
    merchant_id = getattr(settings, "CLICK_MERCHANT_ID", "")
    if not (service_id and merchant_id):
        return ""
    params = {
        "service_id": service_id, "merchant_id": merchant_id,
        "amount": f"{invoice.balance:.2f}", "transaction_param": invoice.pk,
    }
    if request is not None:
        params["return_url"] = (settings.PUBLIC_SITE_URL or request.build_absolute_uri("/").rstrip("/")) + "/tolovlar/"
    return "https://my.click.uz/services/pay?" + urlencode(params)


def payme_pay_url(invoice):
    merchant_id = getattr(settings, "PAYME_MERCHANT_ID", "")
    if not merchant_id:
        return ""
    raw = f"m={merchant_id};ac.invoice_id={invoice.pk};a={to_tiyin(invoice.balance)}"
    host = "https://test.paycom.uz" if getattr(settings, "PAYME_TEST", False) else "https://checkout.paycom.uz"
    return f"{host}/{base64.b64encode(raw.encode()).decode()}"
