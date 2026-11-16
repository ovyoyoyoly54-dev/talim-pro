"""Click (SHOP-API) va Payme (Merchant API) webhook mantiqi."""
import base64
import hashlib
import hmac
import json
import time
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import Invoice, Payment
from .billing import to_tiyin

PAYME_TIMEOUT_MS = 12 * 60 * 60 * 1000


def _now_ms():
    return int(time.time() * 1000)


# ───────────────────────────── Click ─────────────────────────────

CLICK_OK, CLICK_SIGN, CLICK_AMOUNT, CLICK_ACTION = 0, -1, -2, -3
CLICK_PAID, CLICK_NO_USER, CLICK_NO_TX, CLICK_FAIL, CLICK_BAD_REQ, CLICK_CANCELLED = -4, -5, -6, -7, -8, -9


def click_sign(data, *, complete):
    parts = [
        data.get("click_trans_id", ""), data.get("service_id", ""), settings.CLICK_SECRET_KEY,
        data.get("merchant_trans_id", ""),
    ]
    if complete:
        parts.append(data.get("merchant_prepare_id", ""))
    parts += [data.get("amount", ""), data.get("action", ""), data.get("sign_time", "")]
    return hashlib.md5("".join(str(p) for p in parts).encode()).hexdigest()


def _click_reply(data, code, note="", **extra):
    body = {
        "click_trans_id": data.get("click_trans_id"), "merchant_trans_id": data.get("merchant_trans_id"),
        "error": code, "error_note": note or {0: "Success"}.get(code, "Error"),
    }
    body.update(extra)
    return JsonResponse(body)


@csrf_exempt
@require_POST
def click_webhook(request):
    data = {k: v for k, v in request.POST.items()}
    if not (settings.CLICK_SECRET_KEY and settings.CLICK_SERVICE_ID):
        return _click_reply(data, CLICK_FAIL, "Click sozlanmagan")
    required = ("click_trans_id", "service_id", "merchant_trans_id", "amount", "action", "sign_time", "sign_string")
    if any(k not in data for k in required):
        return _click_reply(data, CLICK_BAD_REQ, "Request error")
    action = data["action"]
    if action not in ("0", "1"):
        return _click_reply(data, CLICK_ACTION, "Action not found")
    if data["service_id"] != str(settings.CLICK_SERVICE_ID):
        return _click_reply(data, CLICK_BAD_REQ, "service_id noto‘g‘ri")
    expected = click_sign(data, complete=action == "1")
    if not hmac.compare_digest(expected, data["sign_string"]):
        return _click_reply(data, CLICK_SIGN, "SIGN CHECK FAILED!")
    try:
        amount = Decimal(data["amount"])
    except InvalidOperation:
        return _click_reply(data, CLICK_BAD_REQ, "amount noto‘g‘ri")

    with transaction.atomic():
        try:
            invoice = Invoice.objects.select_for_update().get(pk=int(data["merchant_trans_id"]))
        except (Invoice.DoesNotExist, ValueError):
            return _click_reply(data, CLICK_NO_USER, "Hisob topilmadi")

        if action == "0":  # prepare
            if invoice.status == Invoice.Status.CANCELLED:
                return _click_reply(data, CLICK_CANCELLED, "Hisob bekor qilingan")
            if invoice.balance <= 0:
                return _click_reply(data, CLICK_PAID, "Hisob allaqachon to‘langan")
            if amount != invoice.balance:
                return _click_reply(data, CLICK_AMOUNT, "Summa noto‘g‘ri")
            payment, _ = Payment.objects.get_or_create(
                method=Payment.Method.CLICK, external_id=data["click_trans_id"],
                defaults={"invoice": invoice, "amount": amount, "status": Payment.Status.PENDING},
            )
            if payment.status == Payment.Status.COMPLETED:
                return _click_reply(data, CLICK_PAID, "Allaqachon to‘langan")
            return _click_reply(data, CLICK_OK, merchant_prepare_id=payment.pk)

        # complete
        try:
            payment = Payment.objects.select_for_update().get(
                pk=int(data.get("merchant_prepare_id", "")), invoice=invoice,
                method=Payment.Method.CLICK, external_id=data["click_trans_id"],
            )
        except (Payment.DoesNotExist, ValueError):
            return _click_reply(data, CLICK_NO_TX, "Tranzaksiya topilmadi")
        if payment.amount != amount:
            return _click_reply(data, CLICK_AMOUNT, "Summa noto‘g‘ri")
        if payment.status == Payment.Status.COMPLETED:
            return _click_reply(data, CLICK_PAID, "Allaqachon to‘langan")
        if payment.status == Payment.Status.CANCELLED:
            return _click_reply(data, CLICK_CANCELLED, "Tranzaksiya bekor qilingan")
        if int(data.get("error", 0) or 0) < 0:
            payment.mark_cancelled()
            return _click_reply(data, CLICK_CANCELLED, "Tranzaksiya bekor qilindi")
        payment.mark_completed()
        return _click_reply(data, CLICK_OK, merchant_confirm_id=payment.pk)


# ───────────────────────────── Payme ─────────────────────────────

class PaymeError(Exception):
    MESSAGES = {
        -32504: ("Недостаточно привилегий", "Huquq yetarli emas", "Insufficient privileges"),
        -32300: ("Ошибка в запросе", "So‘rov xato", "Request error"),
        -32600: ("Неверный запрос", "Noto‘g‘ri so‘rov", "Invalid request"),
        -32601: ("Метод не найден", "Metod topilmadi", "Method not found"),
        -31001: ("Неверная сумма", "Summa noto‘g‘ri", "Wrong amount"),
        -31003: ("Транзакция не найдена", "Tranzaksiya topilmadi", "Transaction not found"),
        -31007: ("Невозможно отменить транзакцию", "Tranzaksiyani bekor qilib bo‘lmaydi", "Cannot cancel transaction"),
        -31008: ("Невозможно выполнить операцию", "Amalni bajarib bo‘lmaydi", "Cannot perform operation"),
        -31050: ("Счёт не найден", "Hisob topilmadi", "Invoice not found"),
        -31051: ("Счёт нельзя оплатить", "Hisobni to‘lab bo‘lmaydi", "Invoice is not payable"),
        -31099: ("Счёт занят другой транзакцией", "Hisob boshqa tranzaksiya bilan band", "Invoice is busy"),
    }

    def __init__(self, code, data=None):
        self.code, self.data = code, data
        super().__init__(code)

    def payload(self):
        ru, uz, en = self.MESSAGES.get(self.code, ("Ошибка", "Xatolik", "Error"))
        return {"code": self.code, "message": {"ru": ru, "uz": uz, "en": en}, "data": self.data}


def _payme_authorized(request):
    key = getattr(settings, "PAYME_KEY", "")
    header = request.META.get("HTTP_AUTHORIZATION", "")
    if not key or not header.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(header[6:]).decode()
    except Exception:
        return False
    return hmac.compare_digest(decoded, f"Paycom:{key}")


def _payme_invoice(params, *, lock=False):
    account = params.get("account") or {}
    try:
        invoice_id = int(account.get("invoice_id"))
    except (TypeError, ValueError):
        raise PaymeError(-31050, "invoice_id")
    queryset = Invoice.objects.select_for_update() if lock else Invoice.objects
    invoice = queryset.filter(pk=invoice_id).first()
    if invoice is None:
        raise PaymeError(-31050, "invoice_id")
    return invoice


def _payme_check_perform(params, *, lock=False):
    invoice = _payme_invoice(params, lock=lock)
    amount = params.get("amount")
    if not isinstance(amount, int) or amount <= 0:
        raise PaymeError(-31001)
    if invoice.status == Invoice.Status.CANCELLED or invoice.balance <= 0:
        raise PaymeError(-31051, "invoice_id")
    if amount != to_tiyin(invoice.balance):
        raise PaymeError(-31001)
    return invoice


def _payme_tx(payment_id):
    payment = Payment.objects.select_for_update().filter(method=Payment.Method.PAYME, external_id=payment_id).first()
    if payment is None:
        raise PaymeError(-31003)
    return payment


def _tx_payload(p):
    return {
        "create_time": p.provider_create_ms, "perform_time": p.provider_perform_ms or 0,
        "cancel_time": p.provider_cancel_ms or 0, "transaction": str(p.pk), "state": p.provider_state,
        "reason": p.provider_reason,
    }


def _payme_expired(p):
    return p.provider_state == 1 and _now_ms() - (p.provider_create_ms or 0) > PAYME_TIMEOUT_MS


def _payme_cancel(p, reason):
    state = -1 if p.provider_state == 1 else -2
    p.provider_state, p.provider_reason, p.provider_cancel_ms = state, reason, _now_ms()
    p.status = Payment.Status.CANCELLED
    p.save(update_fields=["provider_state", "provider_reason", "provider_cancel_ms", "status"])
    p.invoice.refresh_status()


def _m_check_perform(params):
    _payme_check_perform(params)
    return {"allow": True}


def _m_create(params):
    pid = params.get("id")
    if not pid or not isinstance(params.get("time"), int):
        raise PaymeError(-32600)
    with transaction.atomic():
        existing = Payment.objects.select_for_update().filter(method=Payment.Method.PAYME, external_id=pid).first()
        if existing is None:
            invoice = _payme_check_perform(params, lock=True)
            if invoice.payments.filter(method=Payment.Method.PAYME, provider_state=1).exists():
                raise PaymeError(-31099, "invoice_id")
            payment = Payment.objects.create(
                invoice=invoice, amount=Decimal(params["amount"]) / 100, method=Payment.Method.PAYME,
                external_id=pid, status=Payment.Status.PENDING, provider_state=1,
                provider_create_ms=params["time"],
            )
            return {"create_time": payment.provider_create_ms, "transaction": str(payment.pk), "state": 1}
        if existing.provider_state != 1:
            raise PaymeError(-31008)
        if not _payme_expired(existing):
            return {"create_time": existing.provider_create_ms, "transaction": str(existing.pk), "state": 1}
        _payme_cancel(existing, 4)
    # Bekor qilish saqlanishi uchun xato tranzaksiyadan tashqarida ko'tariladi.
    raise PaymeError(-31008)


def _m_perform(params):
    with transaction.atomic():
        payment = _payme_tx(params.get("id"))
        if payment.provider_state == 2:
            return {"transaction": str(payment.pk), "perform_time": payment.provider_perform_ms, "state": 2}
        if payment.provider_state != 1:
            raise PaymeError(-31008)
        if not _payme_expired(payment):
            payment.provider_state, payment.provider_perform_ms = 2, _now_ms()
            payment.save(update_fields=["provider_state", "provider_perform_ms"])
            payment.mark_completed()
            return {"transaction": str(payment.pk), "perform_time": payment.provider_perform_ms, "state": 2}
        _payme_cancel(payment, 4)
    # Bekor qilish saqlanishi uchun xato tranzaksiyadan tashqarida ko'tariladi.
    raise PaymeError(-31008)


def _m_cancel(params):
    with transaction.atomic():
        payment = _payme_tx(params.get("id"))
        if payment.provider_state in (-1, -2):
            return {"transaction": str(payment.pk), "cancel_time": payment.provider_cancel_ms, "state": payment.provider_state}
        _payme_cancel(payment, params.get("reason"))
        return {"transaction": str(payment.pk), "cancel_time": payment.provider_cancel_ms, "state": payment.provider_state}


def _m_check(params):
    payment = Payment.objects.filter(method=Payment.Method.PAYME, external_id=params.get("id")).first()
    if payment is None:
        raise PaymeError(-31003)
    return _tx_payload(payment)


def _m_statement(params):
    start, end = params.get("from"), params.get("to")
    if not isinstance(start, int) or not isinstance(end, int):
        raise PaymeError(-32600)
    payments = Payment.objects.filter(
        method=Payment.Method.PAYME, provider_create_ms__gte=start, provider_create_ms__lte=end,
    ).order_by("provider_create_ms")
    return {"transactions": [
        {"id": p.external_id, "time": p.provider_create_ms, "amount": to_tiyin(p.amount),
         "account": {"invoice_id": p.invoice_id}, **_tx_payload(p)}
        for p in payments
    ]}


PAYME_METHODS = {
    "CheckPerformTransaction": _m_check_perform, "CreateTransaction": _m_create,
    "PerformTransaction": _m_perform, "CancelTransaction": _m_cancel,
    "CheckTransaction": _m_check, "GetStatement": _m_statement,
}


@csrf_exempt
@require_POST
def payme_webhook(request):
    try:
        body = json.loads(request.body or b"{}")
    except ValueError:
        return JsonResponse({"error": PaymeError(-32300).payload(), "id": None})
    request_id = body.get("id") if isinstance(body, dict) else None
    if not _payme_authorized(request):
        return JsonResponse({"error": PaymeError(-32504).payload(), "id": request_id})
    handler = PAYME_METHODS.get(body.get("method")) if isinstance(body, dict) else None
    if handler is None:
        return JsonResponse({"error": PaymeError(-32601).payload(), "id": request_id})
    params = body.get("params") if isinstance(body.get("params"), dict) else {}
    try:
        return JsonResponse({"result": handler(params), "id": request_id})
    except PaymeError as exc:
        return JsonResponse({"error": exc.payload(), "id": request_id})
