"""O‘zgarishlar jurnali: veb-so‘rov paytida bo‘lgan model o‘zgarishlari va kirish hodisalari."""
import threading

from django.apps import apps
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from .models import AuditLog
from .utils import get_client_ip

_local = threading.local()

TRACKED = (
    "User", "StudyGroup", "StudentProfile", "Lesson", "GradeRecord", "Attendance", "Invoice", "Payment",
    "Homework", "HomeworkSubmission", "Course", "EnrollmentApplication", "PlatformSettings", "TwoFactorDevice",
)
# Maxfiy yoki shovqinli maydonlar jurnalga yozilmaydi.
SKIP_FIELDS = {"password", "last_login", "updated_at", "secret", "backup_code_hashes", "last_counter", "ip_digest"}


def set_context(request):
    _local.request = request


def clear_context():
    _local.request = None


def current_request():
    return getattr(_local, "request", None)


def _actor(request):
    user = getattr(request, "user", None) if request is not None else None
    return user if user is not None and user.is_authenticated else None


def record(action, *, request=None, user=None, username="", model="", object_id="", object_repr="", changes=None):
    request = request or current_request()
    user = user or _actor(request)
    ip = None
    if request is not None:
        ip = get_client_ip(request) or None
    AuditLog.objects.create(
        user=user, username=(username or (user.get_username() if user else ""))[:150], action=action,
        model=model[:80], object_id=str(object_id)[:40], object_repr=str(object_repr)[:200],
        changes=changes or {}, ip_address=ip,
    )


def _tracked(sender):
    return sender._meta.app_label == "school" and sender.__name__ in TRACKED


def _snapshot(instance):
    data = {}
    for field in instance._meta.concrete_fields:
        if field.name in SKIP_FIELDS:
            continue
        data[field.name] = str(getattr(instance, field.attname, ""))[:200]
    return data


@receiver(pre_save)
def audit_pre_save(sender, instance, raw=False, **kwargs):
    if raw or not _tracked(sender) or current_request() is None:
        return
    instance._audit_before = None
    if instance.pk:
        old = sender._default_manager.filter(pk=instance.pk).first()
        if old is not None:
            instance._audit_before = _snapshot(old)


@receiver(post_save)
def audit_post_save(sender, instance, created, raw=False, **kwargs):
    if raw or not _tracked(sender) or current_request() is None:
        return
    after = _snapshot(instance)
    if created:
        changes = {k: ["", v] for k, v in after.items() if v not in ("", "None")}
        action = AuditLog.Action.CREATE
    else:
        before = getattr(instance, "_audit_before", None) or {}
        changes = {k: [before.get(k, ""), v] for k, v in after.items() if before.get(k) != v}
        if not changes:
            return
        action = AuditLog.Action.UPDATE
    record(action, model=sender.__name__, object_id=instance.pk, object_repr=str(instance), changes=changes)


@receiver(post_delete)
def audit_post_delete(sender, instance, **kwargs):
    if not _tracked(sender) or current_request() is None:
        return
    record(AuditLog.Action.DELETE, model=sender.__name__, object_id=instance.pk, object_repr=str(instance))


@receiver(user_logged_in)
def audit_login(sender, request, user, **kwargs):
    if request is not None:
        request.session.pop("2fa_ok", None)  # har yangi kirishda 2FA qaytadan tekshiriladi
    record(AuditLog.Action.LOGIN, request=request, user=user, username=user.get_username())


@receiver(user_logged_out)
def audit_logout(sender, request, user, **kwargs):
    if user is not None:
        record(AuditLog.Action.LOGOUT, request=request, user=user, username=user.get_username())


@receiver(user_login_failed)
def audit_login_failed(sender, credentials, request=None, **kwargs):
    record(AuditLog.Action.LOGIN_FAILED, request=request, username=str(credentials.get("username", ""))[:150])
