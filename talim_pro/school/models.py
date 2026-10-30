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
    role = models.CharField(max_length=12, choices=Role.choices, default=Role.STUDENT)
    phone = models.CharField(max_length=24, blank=True)
    # For a parent account, students are connected through StudentProfile.parent.

    def __str__(self):
        return self.get_full_name() or self.username

class StudyGroup(models.Model):
    name = models.CharField(max_length=80, unique=True)
    subject = models.CharField(max_length=100)
    teachers = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="teaching_groups", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def clean(self):
        if not self.pk and StudyGroup.objects.count() >= 5:
            raise ValidationError("Ko‘pi bilan 5 ta guruh yaratish mumkin.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} — {self.subject}"

class StudentProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="student_profile")
    group = models.ForeignKey(StudyGroup, on_delete=models.PROTECT, related_name="students")
    parent = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="children")
    joined_on = models.DateField(auto_now_add=True)

    def __str__(self):
        return str(self.user)

class Lesson(models.Model):
    group = models.ForeignKey(StudyGroup, on_delete=models.CASCADE, related_name="lessons")
    title = models.CharField(max_length=120)
    starts_at = models.DateTimeField()
    room = models.CharField(max_length=80, blank=True)
    teacher = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="lessons")

    class Meta:
        ordering = ["starts_at"]

    def clean(self):
        if self.teacher_id and not (self.teacher.is_superuser or self.teacher.role in (User.Role.TEACHER, User.Role.ADMIN)):
            raise ValidationError({"teacher": "Darsga faqat o‘qituvchi biriktirilishi mumkin."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.title} — {self.starts_at:%Y-%m-%d %H:%M}"

class GradeReasonQuerySet(models.QuerySet):
    def delete(self):
        if self.filter(grade_records__score__lt=8).exists():
            raise ValidationError("Past baholarda ishlatilgan sababni o‘chirib bo‘lmaydi. Uni faolsizlantiring.")
        return super().delete()


class GradeReason(models.Model):
    title = models.CharField(max_length=120, unique=True)
    active = models.BooleanField(default=True)
    objects = GradeReasonQuerySet.as_manager()

    class Meta:
        ordering = ["title"]

    def delete(self, *args, **kwargs):
        if self.grade_records.filter(score__lt=8).exists():
            raise ValidationError("Past baholarda ishlatilgan sababni o‘chirib bo‘lmaydi. Uni faolsizlantiring.")
        return super().delete(*args, **kwargs)

    def __str__(self):
        return self.title

class GradeRecord(models.Model):
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="grades")
    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name="grades")
    score = models.PositiveSmallIntegerField()
    reasons = models.ManyToManyField(GradeReason, blank=True, related_name="grade_records")
    note = models.TextField(blank=True, max_length=1000)
    teacher = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="entered_grades")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["lesson", "student"], name="one_grade_per_student_per_lesson"),
            models.CheckConstraint(condition=Q(score__gte=0) & Q(score__lte=10), name="grade_score_0_to_10"),
        ]
        ordering = ["student__user__last_name", "student__user__first_name"]

    def clean(self):
        score = getattr(self, "score", None)
        if score is not None and score < 8:
            if self.pk:
                has_reason = self.reasons.exists()
            else:
                has_reason = bool(getattr(self, "_pending_reasons", None))
            if not has_reason:
                raise ValidationError({"reasons": "8 dan past baho uchun kamida bitta sabab tanlang."})
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
        self.full_clean()
        if self.pk is None and self.score < 8:
            if not pending_reasons:
                raise ValidationError({"reasons": "Past baholi yangi qayd uchun sabab belgilang."})
            score = self.score
            with transaction.atomic():
                self.score = 8
                super().save(*args, **kwargs)
                self.reasons.set(pending_reasons)
                self.score = score
                super().save()
            return
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.student} — {self.score}/10"

class Attendance(models.Model):
    class Status(models.TextChoices):
        PRESENT = "present", "Qatnashdi"
        LATE = "late", "Kechikdi"
        ABSENT = "absent", "Kelmagan"
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="attendance")
    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name="attendance")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PRESENT)
    note = models.CharField(max_length=250, blank=True)
    teacher = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["lesson", "student"], name="one_attendance_per_student_per_lesson")]
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
    parent = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    student = models.ForeignKey(StudentProfile, on_delete=models.SET_NULL, null=True, blank=True)
    body = models.TextField()
    status = models.CharField(max_length=10, choices=Status.choices)
    provider_response = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class PhoneOTP(models.Model):
    class Purpose(models.TextChoices):
        RESET_PASSWORD = "reset_password", "Parolni tiklash"
        CLOSE_ACCOUNT = "close_account", "Akkauntni yopish"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="phone_otps")
    purpose = models.CharField(max_length=20, choices=Purpose.choices)
    code_hash = models.CharField(max_length=128)
    request_ip_digest = models.CharField(max_length=64, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    consumed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["user", "purpose", "created_at"])]

    def __str__(self):
        return f"{self.user_id} — {self.purpose}"
