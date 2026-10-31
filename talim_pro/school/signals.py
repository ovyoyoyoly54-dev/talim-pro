from django.core.exceptions import ValidationError
from django.db.models import Count
from django.db.models.signals import m2m_changed, post_migrate
from django.dispatch import receiver

from .models import GradeRecord


PERMISSION_ACTIONS = {
    "add": "Qo‘shish",
    "change": "O‘zgartirish",
    "delete": "O‘chirish",
    "view": "Ko‘rish",
}


@receiver(post_migrate)
def uzbek_permission_names(sender, app_config, using, **kwargs):
    """Ruxsat (Permission) nomlarini o‘zbekchaga o‘giradi.

    Django ruxsat nomlarini migratsiya paytida ingliz tilida ("Can add lesson"
    kabi) yozib qo‘yadi va ularni tarjima qilmaydi, shuning uchun admin
    panelidagi foydalanuvchi formasida inglizcha matn ko‘rinadi. `post_migrate`
    signali Django ruxsatlarni yaratib bo‘lgandan keyin ishga tushadi.

    Django boshqaruv buyruqlari bajarilayotganda ataylab ingliz tilini yoqadi
    (ma'lumotlar bazasi kontenti tarjima qilinmasligi uchun), shu sababli bu
    yerda tilni ochiq ko‘rsatamiz.
    """
    if app_config is None:
        return
    from django.conf import settings
    from django.contrib.auth.models import Permission
    from django.utils import translation

    changed = []
    with translation.override(settings.LANGUAGE_CODE):
        for permission in Permission.objects.using(using).select_related("content_type"):
            action, separator, _model = permission.codename.partition("_")
            if not separator or action not in PERMISSION_ACTIONS:
                continue
            model_class = permission.content_type.model_class()
            if model_class is None:
                continue
            new_name = f"{PERMISSION_ACTIONS[action]} {model_class._meta.verbose_name}"
            if permission.name != new_name:
                permission.name = new_name
                changed.append(permission)
        if changed:
            Permission.objects.using(using).bulk_update(changed, ["name"])


@receiver(m2m_changed, sender=GradeRecord.reasons.through)
def preserve_low_grade_reason(sender, instance, action, reverse, model, pk_set, **kwargs):
    if action not in {"pre_clear", "pre_remove"}:
        return

    if not reverse:
        if instance.score >= 8:
            return
        if action == "pre_clear":
            raise ValidationError("Avval bahoni 8 yoki undan yuqori qiling yoki boshqa sabab biriktiring.")
        remaining = instance.reasons.exclude(pk__in=pk_set or ()).exists()
        if not remaining:
            raise ValidationError("8 dan past bahoning oxirgi sababini olib tashlab bo‘lmaydi.")
        return

    if action == "pre_clear":
        last_reason = instance.grade_records.filter(score__lt=8).annotate(
            reason_count=Count("reasons")
        ).filter(reason_count=1).exists()
    else:
        last_reason = GradeRecord.objects.filter(
            pk__in=pk_set or (), score__lt=8
        ).annotate(reason_count=Count("reasons")).filter(reason_count=1).exists()
    if last_reason:
        raise ValidationError("Past baholarda ishlatilgan oxirgi sababni olib tashlab bo‘lmaydi.")
