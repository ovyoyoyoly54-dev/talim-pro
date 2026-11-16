from django.conf import settings


def get_client_ip(request):
    """Mijoz IP manzili.

    Standart holatda faqat REMOTE_ADDR ishlatiladi. Ishonchli proksi orqasida
    TRUSTED_PROXY_COUNT ni proksilar soniga qo'ying: shunda X-Forwarded-For
    ro'yxatining oxiridan shuncha qadam ichkaridagi manzil olinadi. Mijoz
    o'zi yuborgan chap tomondagi qiymatlarga ishonilmaydi.
    """
    remote = request.META.get("REMOTE_ADDR", "")
    proxies = getattr(settings, "TRUSTED_PROXY_COUNT", 0)
    if proxies <= 0:
        return remote
    forwarded = [part.strip() for part in request.META.get("HTTP_X_FORWARDED_FOR", "").split(",") if part.strip()]
    if len(forwarded) >= proxies:
        return forwarded[-proxies]
    return remote
