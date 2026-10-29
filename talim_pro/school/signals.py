from django.core.exceptions import ValidationError
from django.db.models import Count
from django.db.models.signals import m2m_changed
from django.dispatch import receiver

from .models import GradeRecord


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
