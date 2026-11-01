from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q

class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "admin", "Administrator"
        TEACHER = "teacher", "O‘qituvchi"
        STUDENT = "student", "O‘quvchi"
        PARENT = "parent", "Ota-ona"
    role = models.CharField("rol", max_length=12, choices=Role.choices, default=Role.STUDENT)
    phone = models.CharField("telefon raqami", max_length=24, blank=True)
    # For a parent account, students are connected through StudentProfile.parent.

    class Meta(AbstractUser.Meta):
        verbose_name = "foydalanuvchi"
        verbose_name_plural = "Foydalanuvchilar"

    def __str__(self):
        return self.get_full_name() or self.username


class PlatformSettings(models.Model):
    site_name = models.CharField("Sayt nomi", max_length=80, default="TA’LIM PRO")
    home_heading = models.CharField("Bosh sahifa sarlavhasi", max_length=160, default="Ta’lim jarayoni bitta joyda.")
    home_description = models.CharField(
        "Bosh sahifa tavsifi", max_length=300,
        default="Dars jadvali, baholar va davomatni tartibli boshqaring.",
    )
    contact_phone = models.CharField("Aloqa telefoni", max_length=24, blank=True)
    contact_email = models.EmailField("Aloqa emaili", blank=True)
    updated_at = models.DateTimeField("Yangilangan vaqt", auto_now=True)

    class Meta:
        verbose_name = "sayt sozlamasi"
        verbose_name_plural = "Sayt sozlamalari"

    @classmethod
    def get_solo(cls):
        settings_obj, _ = cls.objects.get_or_create(pk=1)
        return settings_obj

    def save(self, *args, **kwargs):
        self.pk = 1
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.site_name

class StudyGroup(models.Model):
    name = models.CharField("nomi", max_length=80, unique=True)
    subject = models.CharField("fan", max_length=100)
    teachers = models.ManyToManyField(settings.AUTH_USER_MODEL, verbose_name="o‘qituvchilar", related_name="teaching_groups", blank=True)
    created_at = models.DateTimeField("yaratilgan vaqt", auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "o‘quv guruhi"
        verbose_name_plural = "O‘quv guruhlari"

    def clean(self):
        if not self.pk and StudyGroup.objects.count() >= 5:
            raise ValidationError("Ko‘pi bilan 5 ta guruh yaratish mumkin.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} — {self.subject}"

class StudentProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, verbose_name="foydalanuvchi", on_delete=models.CASCADE, related_name="student_profile")
    group = models.ForeignKey(StudyGroup, verbose_name="guruh", on_delete=models.PROTECT, related_name="students")
    parent = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="ota-ona", on_delete=models.SET_NULL, null=True, blank=True, related_name="children")
    parent_phone = models.CharField("ota-onaning SMS raqami", max_length=24, blank=True)
    joined_on = models.DateField("qo‘shilgan sana", auto_now_add=True)

    class Meta:
        verbose_name = "o‘quvchi profili"
        verbose_name_plural = "O‘quvchilar"

    def __str__(self):
        return str(self.user)

class Lesson(models.Model):
    group = models.ForeignKey(StudyGroup, verbose_name="guruh", on_delete=models.CASCADE, related_name="lessons")
    title = models.CharField("mavzu", max_length=120)
    starts_at = models.DateTimeField("boshlanish vaqti")
    room = models.CharField("xona", max_length=80, blank=True)
    teacher = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="o‘qituvchi", on_delete=models.PROTECT, related_name="lessons")

    class Meta:
        ordering = ["starts_at"]
        verbose_name = "dars"
        verbose_name_plural = "Darslar"

    def clean(self):
        errors = {}
        teacher = self.teacher if self.teacher_id else None
        if teacher and not (teacher.is_superuser or teacher.role in (User.Role.TEACHER, User.Role.ADMIN)):
            errors["teacher"] = "Darsga faqat o‘qituvchi biriktirilishi mumkin."
        elif teacher and self.group_id and teacher.role == User.Role.TEACHER:
            if not self.group.teachers.filter(pk=teacher.pk).exists():
                errors["teacher"] = "Tanlangan o‘qituvchi bu guruhga biriktirilmagan."

        if self.starts_at:
            conflicts = Lesson.objects.filter(starts_at=self.starts_at)
            if self.pk:
                conflicts = conflicts.exclude(pk=self.pk)
            if self.group_id and conflicts.filter(group_id=self.group_id).exists():
                errors["group"] = "Bu guruhda aynan shu vaqtda dars mavjud."
            if self.teacher_id and conflicts.filter(teacher_id=self.teacher_id).exists():
                errors["teacher"] = "O‘qituvchining aynan shu vaqtda boshqa darsi bor."
            if self.room.strip() and conflicts.filter(room__iexact=self.room.strip()).exists():
                errors["room"] = "Bu xona aynan shu vaqtda band."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.title} — {self.starts_at:%Y-%m-%d %H:%M}"

class GradeReasonQuerySet(models.QuerySet):
    def delete(self):
        if self.filter(grade_records__score__lte=8).exists():
            raise ValidationError("Past baholarda ishlatilgan sababni o‘chirib bo‘lmaydi. Uni faolsizlantiring.")
        return super().delete()


class GradeReason(models.Model):
    title = models.CharField("nomi", max_length=120, unique=True)
    active = models.BooleanField("faol", default=True)
    objects = GradeReasonQuerySet.as_manager()

    class Meta:
        ordering = ["title"]
        verbose_name = "baho sababi"
        verbose_name_plural = "Baho sabablari"

    def delete(self, *args, **kwargs):
        if self.grade_records.filter(score__lte=8).exists():
            raise ValidationError("Past baholarda ishlatilgan sababni o‘chirib bo‘lmaydi. Uni faolsizlantiring.")
        return super().delete(*args, **kwargs)

    def __str__(self):
        return self.title

class GradeRecord(models.Model):
    lesson = models.ForeignKey(Lesson, verbose_name="dars", on_delete=models.CASCADE, related_name="grades")
    student = models.ForeignKey(StudentProfile, verbose_name="o‘quvchi", on_delete=models.CASCADE, related_name="grades")
    score = models.PositiveSmallIntegerField("baho")
    reasons = models.ManyToManyField(GradeReason, verbose_name="sabablar", blank=True, related_name="grade_records")
    note = models.TextField("izoh", blank=True, max_length=1000)
    teacher = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="o‘qituvchi", on_delete=models.PROTECT, related_name="entered_grades")
    updated_at = models.DateTimeField("yangilangan vaqt", auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["lesson", "student"], name="one_grade_per_student_per_lesson"),
            models.CheckConstraint(condition=Q(score__gte=0) & Q(score__lte=10), name="grade_score_0_to_10"),
        ]
        ordering = ["student__user__last_name", "student__user__first_name"]
        verbose_name = "baho qaydi"
        verbose_name_plural = "Baholar"

    def clean(self):
        score = getattr(self, "score", None)
        pending_reasons = getattr(self, "_pending_reasons", None)
        if score is not None and score <= 8:
            has_reason = bool(pending_reasons) if pending_reasons is not None else (self.pk and self.reasons.exists())
            if not has_reason:
                raise ValidationError({"reasons": "8 yoki undan past baho uchun kamida bitta sabab tanlang."})
        if self.lesson_id and self.student_id and self.lesson.group_id != self.student.group_id:
            raise ValidationError("O‘quvchi ushbu dars guruhiga tegishli emas.")
        if self.lesson_id and self.teacher_id:
            teacher = self.teacher
            if teacher.is_superuser or teacher.role == User.Role.ADMIN:
                return
            if teacher.role != User.Role.TEACHER:
                raise ValidationError({"teacher": "Bahoni faqat o‘qituvchi yoki administrator kiritishi mumkin."})
            if teacher.id != self.lesson.teacher_id or not self.lesson.group.teachers.filter(id=teacher.id).exists():
                raise ValidationError({"teacher": "O‘qituvchi ushbu darsga biriktirilmagan."})

    def save(self, *args, **kwargs):
        pending_reasons = getattr(self, "_pending_reasons", None)
        if self.score <= 8 and pending_reasons is not None:
            final_score = self.score
            self.score = 9
            super().save(*args, **kwargs)
            self.reasons.set(pending_reasons)
            self.score = final_score
            self._pending_reasons = None
            self.full_clean()
            return super().save()
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.student} — {self.score}/10"

class Attendance(models.Model):
    class Status(models.TextChoices):
        PRESENT = "present", "Qatnashdi"
        LATE = "late", "Kechikdi"
        ABSENT = "absent", "Kelmagan"
    lesson = models.ForeignKey(Lesson, verbose_name="dars", on_delete=models.CASCADE, related_name="attendance")
    student = models.ForeignKey(StudentProfile, verbose_name="o‘quvchi", on_delete=models.CASCADE, related_name="attendance")
    status = models.CharField("holati", max_length=10, choices=Status.choices, default=Status.PRESENT)
    note = models.CharField("izoh", max_length=250, blank=True)
    teacher = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="o‘qituvchi", on_delete=models.PROTECT)
    updated_at = models.DateTimeField("yangilangan vaqt", auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["lesson", "student"], name="one_attendance_per_student_per_lesson")]
        verbose_name = "davomat qaydi"
        verbose_name_plural = "Davomat"
    def clean(self):
        if self.lesson_id and self.student_id and self.lesson.group_id != self.student.group_id:
            raise ValidationError("O‘quvchi ushbu dars guruhiga tegishli emas.")
        if self.teacher_id:
            teacher = self.teacher
            if teacher.is_superuser or teacher.role == User.Role.ADMIN:
                return
            if teacher.role != User.Role.TEACHER:
                raise ValidationError({"teacher": "Davomatni faqat o‘qituvchi yoki administrator kiritishi mumkin."})
            if self.lesson_id and (teacher.id != self.lesson.teacher_id or not self.lesson.group.teachers.filter(id=teacher.id).exists()):
                raise ValidationError({"teacher": "O‘qituvchi ushbu darsga biriktirilmagan."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

class SMSLog(models.Model):
    class Status(models.TextChoices):
        SENT = "sent", "Yuborildi"
        FAILED = "failed", "Xatolik"
        DISABLED = "disabled", "Sozlanmagan"
    parent = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="ota-ona", on_delete=models.SET_NULL, null=True, blank=True)
    student = models.ForeignKey(StudentProfile, verbose_name="o‘quvchi", on_delete=models.SET_NULL, null=True, blank=True)
    body = models.TextField("xabar matni")
    status = models.CharField("holati", max_length=10, choices=Status.choices)
    provider_response = models.TextField("provayder javobi", blank=True)
    created_at = models.DateTimeField("yaratilgan vaqt", auto_now_add=True)

    class Meta:
        verbose_name = "SMS jurnali"
        verbose_name_plural = "SMS jurnali"


class PhoneOTP(models.Model):
    class Purpose(models.TextChoices):
        SIGNUP = "signup", "Yangi akkaunt"
        RESET_PASSWORD = "reset_password", "Parolni tiklash"
        CLOSE_ACCOUNT = "close_account", "Akkauntni yopish"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="foydalanuvchi", on_delete=models.CASCADE, related_name="phone_otps")
    purpose = models.CharField("maqsad", max_length=20, choices=Purpose.choices)
    code_hash = models.CharField("kod xeshi", max_length=128)
    request_ip_digest = models.CharField("so‘rov IP xeshi", max_length=64, blank=True, db_index=True)
    created_at = models.DateTimeField("yaratilgan vaqt", auto_now_add=True, db_index=True)
    expires_at = models.DateTimeField("amal qilish muddati")
    attempts = models.PositiveSmallIntegerField("urinishlar soni", default=0)
    consumed_at = models.DateTimeField("ishlatilgan vaqt", null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["user", "purpose", "created_at"])]

    def __str__(self):
        return f"{self.user_id} — {self.purpose}"
