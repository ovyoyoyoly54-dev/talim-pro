from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
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
        if self.teacher_id and self.teacher.role != User.Role.TEACHER and self.teacher.role != User.Role.ADMIN:
            raise ValidationError({"teacher": "Darsga faqat o‘qituvchi biriktirilishi mumkin."})

    def __str__(self):
        return f"{self.title} — {self.starts_at:%Y-%m-%d %H:%M}"

class GradeReason(models.Model):
    title = models.CharField(max_length=120, unique=True)
    active = models.BooleanField(default=True)
    class Meta:
        ordering = ["title"]
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
        if self.score < 8 and self.pk and not self.reasons.exists():
            raise ValidationError("8 dan past baho uchun kamida bitta sabab tanlang.")
        if self.lesson_id and self.student_id and self.lesson.group_id != self.student.group_id:
            raise ValidationError("O‘quvchi ushbu dars guruhiga tegishli emas.")

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
