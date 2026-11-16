import json

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import Notification, PushSubscription
from .notifications import push_enabled


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
    Notification.objects.filter(user=request.user, read_at__isnull=True).update(read_at=timezone.now())
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
    if not (isinstance(endpoint, str) and endpoint.startswith("https://") and len(endpoint) <= 600
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
        endpoint = ""
    PushSubscription.objects.filter(user=request.user, endpoint=endpoint).delete()
    return JsonResponse({"ok": True})
