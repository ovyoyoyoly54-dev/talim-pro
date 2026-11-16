from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.urls import reverse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import billing
from .models import Invoice, Payment, StudyGroup, StudentProfile, User
from .views import is_admin, posted_object_or_404

MANUAL_METHODS = {Payment.Method.CASH, Payment.Method.CARD, Payment.Method.TRANSFER}


@login_required
def payments_entry(request):
    """Administrator uchun umumiy ko‘rinish, o‘quvchi va ota-ona uchun shaxsiy hisoblar."""
    if is_admin(request.user):
        return payments_overview(request)
    return my_payments(request)


def payments_overview(request):
    period = billing.parse_period(request.GET.get("period")) or billing.first_of_month()
    status = request.GET.get("status", "")
    invoices = Invoice.objects.filter(period=period).select_related("student__user", "student__group")
    if status in Invoice.Status.values:
        invoices = invoices.filter(status=status)
    return render(request, "school/payments.html", {
        "period": period, "status": status, "statuses": Invoice.Status.choices,
        "invoices": invoices.order_by("student__user__last_name", "student__user__first_name"),
        "summary": billing.month_summary(period), "groups": StudyGroup.objects.all(),
        "manual_methods": [(m.value, m.label) for m in Payment.Method if m in MANUAL_METHODS],
        "today": timezone.localdate(),
    })


@login_required
@require_POST
def generate_invoices_view(request):
    if not is_admin(request.user):
        raise PermissionDenied
    period = billing.parse_period(request.POST.get("period"))
    if period is None:
        messages.error(request, "Davr noto‘g‘ri. Oy tanlang.")
        return redirect("payments_overview")
    group = None
    if request.POST.get("group"):
        group = posted_object_or_404(StudyGroup, request.POST["group"])
    created, skipped = billing.generate_invoices(period, group=group)
    from .notifications import notify_invoice_created
    notify_invoice_created(created)
    if created or skipped:
        messages.success(request, f"{len(created)} ta hisob yaratildi, {skipped} tasi avvaldan mavjud.")
    else:
        messages.warning(request, "Hisob yaratilmadi: oylik to‘lovi belgilangan guruhda faol o‘quvchi topilmadi. "
                                  "Guruhning oylik to‘lov summasini kiriting.")
    return redirect(f"{reverse('payments_overview')}?period={period:%Y-%m}")


@login_required
@require_POST
def record_payment(request, invoice_id):
    if not is_admin(request.user):
        raise PermissionDenied
    with transaction.atomic():
        invoice = get_object_or_404(Invoice.objects.select_for_update(), pk=invoice_id)
        method = request.POST.get("method")
        try:
            amount = Decimal(request.POST.get("amount", "").replace(" ", "").replace(",", "."))
        except InvalidOperation:
            amount = Decimal("0")
        if not amount.is_finite():  # "NaN" / "Infinity" taqqoslashda xato beradi
            amount = Decimal("0")
        if method not in MANUAL_METHODS:
            messages.error(request, "To‘lov usuli noto‘g‘ri.")
        elif invoice.status == Invoice.Status.CANCELLED:
            messages.error(request, "Bekor qilingan hisobga to‘lov kiritib bo‘lmaydi.")
        elif amount <= 0 or amount > invoice.balance:
            messages.error(request, f"Summa 0 dan katta va qoldiq ({invoice.balance:.0f} so‘m) dan oshmasligi kerak.")
        else:
            payment = Payment.objects.create(
                invoice=invoice, amount=amount, method=method, created_by=request.user,
                note=request.POST.get("note", "")[:250],
            )
            payment.mark_completed()
            from .notifications import notify_payment_received
            notify_payment_received(payment)
            messages.success(request, f"{amount:.0f} so‘m to‘lov qabul qilindi.")
    return redirect(f"/tolovlar/?period={invoice.period:%Y-%m}")


@login_required
@require_POST
def cancel_invoice(request, invoice_id):
    if not is_admin(request.user):
        raise PermissionDenied
    invoice = get_object_or_404(Invoice, pk=invoice_id)
    if invoice.payments.filter(status=Payment.Status.COMPLETED).exists():
        messages.error(request, "To‘lov qabul qilingan hisobni bekor qilib bo‘lmaydi.")
    else:
        invoice.status = Invoice.Status.CANCELLED
        invoice.save(update_fields=["status"])
        messages.success(request, "Hisob bekor qilindi.")
    return redirect(f"/tolovlar/?period={invoice.period:%Y-%m}")


@login_required
def debtors_list(request):
    if not is_admin(request.user):
        raise PermissionDenied
    rows = billing.debtors()
    return render(request, "school/debtors.html", {
        "rows": rows, "total_debt": sum((r["debt"] for r in rows), Decimal("0")),
    })


@login_required
@require_POST
def remind_debtors(request):
    if not is_admin(request.user):
        raise PermissionDenied
    from .notifications import notify_debt_reminder
    sent = notify_debt_reminder(billing.debtors())
    messages.success(request, f"{sent} ta qarzdorlik eslatmasi yuborildi.")
    return redirect("debtors_list")


@login_required
def my_payments(request):
    user = request.user
    if user.role == User.Role.STUDENT:
        profiles = StudentProfile.objects.filter(user=user)
    elif user.role == User.Role.PARENT:
        profiles = StudentProfile.objects.filter(parent=user)
    else:
        raise PermissionDenied
    invoices = list(Invoice.objects.filter(student__in=profiles).exclude(
        status=Invoice.Status.CANCELLED).select_related("student__user", "student__group"))
    for invoice in invoices:
        invoice.click_url = billing.click_pay_url(invoice, request) if invoice.balance > 0 else ""
        invoice.payme_url = billing.payme_pay_url(invoice) if invoice.balance > 0 else ""
    payments = Payment.objects.filter(invoice__student__in=profiles, status=Payment.Status.COMPLETED).select_related(
        "invoice__student__user")[:20]
    return render(request, "school/my_payments.html", {
        "invoices": invoices, "payments": payments,
        "debt": sum((i.balance for i in invoices if i.is_overdue), Decimal("0")),
    })
