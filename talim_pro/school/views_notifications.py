import json
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from .models import Notification, PushSubscription
from .notifications import push_enabled


def is_allowed_push_endpoint(endpoint):
    """Push endpoint serverdan so'rov yuboriladigan manzil bo'lgani uchun (SSRF) faqat
    ma'lum brauzer push xizmatlariga ruxsat beriladi."""
    try:
        parts = urlsplit(endpoint)
        host = (parts.hostname or "").lower()
    except ValueError:
        return False
    if parts.scheme != "https" or not host or parts.username or parts.password or parts.port not in (None, 443):
        return False
    return any(host == suffix or host.endswith("." + suffix) for suffix in settings.PUSH_ALLOWED_HOSTS)


@login_required
def notification_list(request):
    items = Notification.objects.filter(user=request.user)[:50]
    return render(request, "school/notifications.html", {
        "items": items, "push_enabled": push_enabled(),
        "vapid_public_key": settings.VAPID_PUBLIC_KEY,
        "has_subscription": request.user.push_subscriptions.exists(),
    })


@login_required
@require_POST
def notifications_mark_read(request):
    updated = Notification.objects.filter(user=request.user, read_at__isnull=True).update(read_at=timezone.now())
    if updated:
        messages.success(request, _("Barcha xabarlar o‘qilgan deb belgilandi."))
    else:
        messages.info(request, _("Yangi xabarlar yo‘q."))
    return redirect("notification_list")


@login_required
@require_POST
def push_subscribe(request):
    if not push_enabled():
        return JsonResponse({"ok": False, "error": "push_disabled"}, status=503)
    try:
        data = json.loads(request.body)
        endpoint = data["endpoint"]
        keys = data["keys"]
        p256dh, auth = keys["p256dh"], keys["auth"]
    except (ValueError, KeyError, TypeError):
        return JsonResponse({"ok": False, "error": "bad_request"}, status=400)
    if not (isinstance(endpoint, str) and len(endpoint) <= 600 and is_allowed_push_endpoint(endpoint)
            and isinstance(p256dh, str) and isinstance(auth, str)):
        return JsonResponse({"ok": False, "error": "bad_request"}, status=400)
    PushSubscription.objects.update_or_create(
        endpoint=endpoint, defaults={"user": request.user, "p256dh": p256dh[:200], "auth": auth[:100]},
    )
    return JsonResponse({"ok": True})


@login_required
@require_POST
def push_unsubscribe(request):
    try:
        endpoint = json.loads(request.body).get("endpoint", "")
    except (ValueError, AttributeError):
        return JsonResponse({"ok": False, "error": "bad_request"}, status=400)
    if not isinstance(endpoint, str):
        return JsonResponse({"ok": False, "error": "bad_request"}, status=400)
    PushSubscription.objects.filter(user=request.user, endpoint=endpoint).delete()
    return JsonResponse({"ok": True})
