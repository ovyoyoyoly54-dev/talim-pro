from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from . import audit, twofactor
from .models import AuditLog, TwoFactorDevice


def _next_url(request):
    target = request.POST.get("next") or request.GET.get("next") or ""
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return target
    return reverse("dashboard")


def _passed(request, user, how):
    request.session[twofactor.SESSION_KEY] = True
    request.session.cycle_key()
    twofactor.clear_failures(user)
    audit.record(AuditLog.Action.TWO_FACTOR, request=request, user=user, object_repr=how)


@never_cache
@login_required
def two_factor_setup(request):
    user = request.user
    device = TwoFactorDevice.objects.filter(user=user).first()
    if device and device.confirmed:
        # Allaqachon sozlangan: faqat tekshiruv sahifasiga yo'naltiramiz.
        return redirect("two_factor_verify")
    if request.method == "POST":
        secret = request.session.get("2fa_pending_secret")
        if not secret:
            return redirect("two_factor_setup")
        if twofactor.is_locked(user):
            messages.error(request, _("Juda ko‘p noto‘g‘ri urinish. 10 daqiqadan so‘ng qayta urinib ko‘ring."))
        else:
            counter = twofactor.check_totp(secret, request.POST.get("code"))
            if counter is None:
                twofactor.register_failure(user)
                messages.error(request, _("Kod noto‘g‘ri. Ilovadagi joriy kodni kiriting."))
            else:
                codes, hashes = twofactor.make_backup_codes()
                TwoFactorDevice.objects.update_or_create(user=user, defaults={
                    "secret": secret, "confirmed": True, "last_counter": counter, "backup_code_hashes": hashes})
                request.session.pop("2fa_pending_secret", None)
                _passed(request, user, "setup")
                return render(request, "school/two_factor_codes.html", {"codes": codes, "next": _next_url(request)})
    secret = request.session.get("2fa_pending_secret")
    if not secret:
        secret = twofactor.new_secret()
        request.session["2fa_pending_secret"] = secret
    uri = twofactor.provisioning_uri(user, secret)
    return render(request, "school/two_factor_setup.html", {
        "secret": secret, "qr": twofactor.qr_data_uri(uri), "next": _next_url(request),
        "two_factor_enforced": twofactor.is_enforced(user),
    })


@never_cache
@login_required
def two_factor_verify(request):
    user = request.user
    if not twofactor.requires_two_factor(user):
        return redirect("dashboard")
    device = TwoFactorDevice.objects.filter(user=user, confirmed=True).first()
    if device is None:
        return redirect("two_factor_setup")
    if request.session.get(twofactor.SESSION_KEY):
        return redirect(_next_url(request))
    if request.method == "POST":
        if twofactor.is_locked(user):
            messages.error(request, _("Juda ko‘p noto‘g‘ri urinish. 10 daqiqadan so‘ng qayta urinib ko‘ring."))
        else:
            code = request.POST.get("code", "")
            counter = twofactor.check_totp(device.secret, code, device.last_counter)
            if counter is not None:
                device.last_counter = counter
                device.save(update_fields=["last_counter"])
                _passed(request, user, "totp")
                return redirect(_next_url(request))
            if twofactor.use_backup_code(device, code):
                _passed(request, user, "backup_code")
                messages.warning(request, _("Zaxira kod ishlatildi. Qolgan kodlar: %(n)s.") % {"n": len(device.backup_code_hashes)})
                return redirect(_next_url(request))
            twofactor.register_failure(user)
            messages.error(request, _("Kod noto‘g‘ri."))
    return render(request, "school/two_factor_verify.html", {"next": _next_url(request), "two_factor_enforced": twofactor.is_enforced(user)})


@never_cache
@login_required
@require_POST
def two_factor_disable(request):
    """Ixtiyoriy 2FA ni o'chirish: joriy parol va joriy kod (yoki zaxira kod) talab qilinadi."""
    user = request.user
    section = reverse("settings_panel") + "#ikki-bosqich"
    device = TwoFactorDevice.objects.filter(user=user, confirmed=True).first()
    if device is None:
        messages.info(request, _("Sizda 2FA yoqilmagan."))
        return redirect(section)
    if twofactor.is_enforced(user):
        messages.error(request, _("Administrator uchun 2FA majburiy, uni o‘chirib bo‘lmaydi."))
        return redirect(section)
    if twofactor.is_locked(user):
        messages.error(request, _("Juda ko‘p noto‘g‘ri urinish. 10 daqiqadan so‘ng qayta urinib ko‘ring."))
        return redirect(section)
    password = request.POST.get("password", "")
    code = request.POST.get("code", "")
    if not user.check_password(password):
        twofactor.register_failure(user)
        messages.error(request, _("Parol noto‘g‘ri."))
        return redirect(section)
    if twofactor.check_totp(device.secret, code, device.last_counter) is None and not twofactor.use_backup_code(device, code):
        twofactor.register_failure(user)
        messages.error(request, _("Kod noto‘g‘ri."))
        return redirect(section)
    device.delete()
    twofactor.clear_failures(user)
    audit.record(AuditLog.Action.TWO_FACTOR, request=request, user=user, object_repr="disabled")
    messages.success(request, _("2FA o‘chirildi."))
    return redirect(section)
