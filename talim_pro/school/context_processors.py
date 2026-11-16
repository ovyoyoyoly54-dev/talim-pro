from .models import Notification, PlatformSettings


def platform_settings(request):
    unread = 0
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        unread = Notification.objects.filter(user=user, read_at__isnull=True).count()
    return {"platform_settings": PlatformSettings.objects.filter(pk=1).first(), "unread_notifications": unread}
