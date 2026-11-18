"""Xavfsizlik sarlavhalari: CSP (nonce bilan), Permissions-Policy va kesh nazorati."""
import secrets

from django.conf import settings
from django.utils.cache import patch_cache_control

PERMISSIONS_POLICY = (
    "accelerometer=(), camera=(), geolocation=(), gyroscope=(), magnetometer=(), "
    "microphone=(), payment=(), usb=(), interest-cohort=()"
)


def build_csp(nonce):
    """Faqat o'z domenidan skript; inline skript faqat nonce bilan ruxsat etiladi."""
    return "; ".join([
        "default-src 'self'",
        f"script-src 'self' 'nonce-{nonce}'",
        # Shablonlarda style="" atributlari ishlatiladi, shuning uchun inline uslub ruxsat etiladi.
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data:",
        "font-src 'self'",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ])


class SecurityHeadersMiddleware:
    """Har bir javobga qo'shimcha himoya sarlavhalarini qo'yadi.

    * Content-Security-Policy — XSS ta'sirini cheklaydi (har so'rovga yangi nonce).
    * Permissions-Policy — kerak bo'lmagan brauzer imkoniyatlarini o'chiradi.
    * Cache-Control: no-store — tizimga kirgan foydalanuvchi sahifalari brauzer
      keshida (masalan, "Orqaga" tugmasi yoki umumiy kompyuter) qolib ketmasin.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.csp_nonce = secrets.token_urlsafe(16)
        response = self.get_response(request)
        if "Content-Security-Policy" not in response:
            response["Content-Security-Policy"] = build_csp(request.csp_nonce)
        response.setdefault("Permissions-Policy", PERMISSIONS_POLICY)
        response.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        user = getattr(request, "user", None)
        if (
            user is not None and user.is_authenticated
            and "Cache-Control" not in response
            and not request.path.startswith(settings.STATIC_URL)
        ):
            patch_cache_control(response, no_store=True, private=True)
        return response
