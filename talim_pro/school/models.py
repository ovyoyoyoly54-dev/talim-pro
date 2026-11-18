from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
import os

from django.core.validators import FileExtensionValidator
from django.db import models, transaction
from django.db.models import Q, Sum
from django.utils import timezone

class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "admin", "Administrator"
        TEACHER = "teacher", "O‘qituvchi"
        STUDENT = "student", "O‘quvchi"
        PARENT = "parent", "Ota-ona"
    role = models.CharField("rol", max_length=12, choices=Role.choices, default=Role.STUDENT)
    phone = models.CharField("telefon raqami", max_length=24, blank=True)
    must_change_credentials = models.BooleanField("login va parolni almashtirishi kerak", default=False)
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
    monthly_fee = models.DecimalField("oylik to‘lov (so‘m)", max_digits=12, decimal_places=2, default=0)
    created_at = models.DateTimeField("yaratilgan vaqt", auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "o‘quv guruhi"
        verbose_name_plural = "O‘quv guruhlari"

    def clean(self):
        limit = getattr(settings, "MAX_STUDY_GROUPS", 5)
        if limit and not self.pk and StudyGroup.objects.count() >= limit:
            raise ValidationError(f"Ko‘pi bilan {limit} ta guruh yaratish mumkin.")

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
            # Vaqtinchalik 9 baho va sabablar bitta tranzaksiyada saqlanadi:
            # yakuniy tekshiruv xato bersa, bazada noto'g'ri baho qolmaydi.
            with transaction.atomic():
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



class Invoice(models.Model):
    """O‘quvchining bir oy uchun to‘lov hisobi."""

    class Status(models.TextChoices):
        UNPAID = "unpaid", "To‘lanmagan"
        PARTIAL = "partial", "Qisman to‘langan"
        PAID = "paid", "To‘langan"
        CANCELLED = "cancelled", "Bekor qilingan"

    student = models.ForeignKey(StudentProfile, verbose_name="o‘quvchi", on_delete=models.PROTECT, related_name="invoices")
    period = models.DateField("davr (oyning 1-sanasi)")
    amount = models.DecimalField("summa (so‘m)", max_digits=12, decimal_places=2)
    due_date = models.DateField("to‘lov muddati")
    status = models.CharField("holati", max_length=10, choices=Status.choices, default=Status.UNPAID)
    note = models.CharField("izoh", max_length=250, blank=True)
    created_at = models.DateTimeField("yaratilgan vaqt", auto_now_add=True)

    class Meta:
        ordering = ["-period", "student__user__last_name"]
        constraints = [
            models.UniqueConstraint(fields=["student", "period"], name="one_invoice_per_student_per_month"),
            models.CheckConstraint(condition=Q(amount__gt=0), name="invoice_amount_positive"),
        ]
        verbose_name = "to‘lov hisobi"
        verbose_name_plural = "To‘lov hisoblari"

    @property
    def paid_amount(self):
        return self.payments.filter(status=Payment.Status.COMPLETED).aggregate(v=Sum("amount"))["v"] or 0

    @property
    def balance(self):
        if self.status == self.Status.CANCELLED:
            return 0
        return max(self.amount - self.paid_amount, 0)

    @property
    def is_overdue(self):
        return self.balance > 0 and self.due_date < timezone.localdate()

    def refresh_status(self, save=True):
        if self.status == self.Status.CANCELLED:
            return self.status
        paid = self.paid_amount
        if paid >= self.amount:
            self.status = self.Status.PAID
        elif paid > 0:
            self.status = self.Status.PARTIAL
        else:
            self.status = self.Status.UNPAID
        if save:
            self.save(update_fields=["status"])
        return self.status

    def __str__(self):
        return f"{self.student} — {self.period:%Y-%m} — {self.amount}"


class Payment(models.Model):
    class Method(models.TextChoices):
        CASH = "cash", "Naqd"
        CARD = "card", "Karta (terminal)"
        TRANSFER = "transfer", "Bank o‘tkazmasi"
        CLICK = "click", "Click"
        PAYME = "payme", "Payme"

    class Status(models.TextChoices):
        PENDING = "pending", "Kutilmoqda"
        COMPLETED = "completed", "To‘langan"
        CANCELLED = "cancelled", "Bekor qilingan"

    invoice = models.ForeignKey(Invoice, verbose_name="hisob", on_delete=models.PROTECT, related_name="payments")
    amount = models.DecimalField("summa (so‘m)", max_digits=12, decimal_places=2)
    method = models.CharField("usul", max_length=10, choices=Method.choices)
    status = models.CharField("holati", max_length=10, choices=Status.choices, default=Status.PENDING)
    external_id = models.CharField("provayder tranzaksiya raqami", max_length=64, blank=True, db_index=True)
    # Payme holati: 1 yaratilgan, 2 bajarilgan, -1/-2 bekor qilingan. Click uchun ishlatilmaydi.
    provider_state = models.SmallIntegerField("provayder holati", null=True, blank=True)
    provider_create_ms = models.BigIntegerField(null=True, blank=True)
    provider_perform_ms = models.BigIntegerField(null=True, blank=True)
    provider_cancel_ms = models.BigIntegerField(null=True, blank=True)
    provider_reason = models.SmallIntegerField(null=True, blank=True)
    note = models.CharField("izoh", max_length=250, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="kiritgan", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField("yaratilgan vaqt", auto_now_add=True)
    paid_at = models.DateTimeField("to‘langan vaqt", null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["method", "external_id"], condition=~Q(external_id=""),
                name="unique_provider_transaction",
            ),
            models.CheckConstraint(condition=Q(amount__gt=0), name="payment_amount_positive"),
        ]
        verbose_name = "to‘lov"
        verbose_name_plural = "To‘lovlar"

    def mark_completed(self, when=None):
        self.status = self.Status.COMPLETED
        self.paid_at = when or timezone.now()
        self.save(update_fields=["status", "paid_at"])
        self.invoice.refresh_status()

    def mark_cancelled(self):
        self.status = self.Status.CANCELLED
        self.save(update_fields=["status"])
        self.invoice.refresh_status()

    def __str__(self):
        return f"{self.invoice_id} — {self.amount} ({self.get_method_display()})"



class Notification(models.Model):
    """Ilova ichidagi xabar; push va SMS xarajatini kamaytirish uchun asosiy kanal."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="foydalanuvchi", on_delete=models.CASCADE, related_name="notifications")
    title = models.CharField("sarlavha", max_length=120)
    body = models.CharField("matn", max_length=400, blank=True)
    url = models.CharField("havola", max_length=200, blank=True)
    created_at = models.DateTimeField("yaratilgan vaqt", auto_now_add=True)
    read_at = models.DateTimeField("o‘qilgan vaqt", null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "read_at"])]
        verbose_name = "bildirishnoma"
        verbose_name_plural = "Bildirishnomalar"

    def __str__(self):
        return f"{self.user_id}: {self.title}"


class PushSubscription(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="foydalanuvchi", on_delete=models.CASCADE, related_name="push_subscriptions")
    endpoint = models.CharField("endpoint", max_length=600, unique=True)
    p256dh = models.CharField(max_length=200)
    auth = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "push obunasi"
        verbose_name_plural = "Push obunalari"

    def __str__(self):
        return f"{self.user_id} — {self.endpoint[:40]}"



HOMEWORK_EXTENSIONS = ["pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt", "jpg", "jpeg", "png", "zip"]
HOMEWORK_MAX_BYTES = 10 * 1024 * 1024


def validate_homework_file(value):
    if value.size > HOMEWORK_MAX_BYTES:
        raise ValidationError("Fayl hajmi 10 MB dan oshmasligi kerak.")


class Homework(models.Model):
    group = models.ForeignKey(StudyGroup, verbose_name="guruh", on_delete=models.CASCADE, related_name="homeworks")
    lesson = models.ForeignKey(Lesson, verbose_name="dars", on_delete=models.SET_NULL, null=True, blank=True, related_name="homeworks")
    title = models.CharField("sarlavha", max_length=140)
    description = models.TextField("topshiriq matni", blank=True, max_length=4000)
    attachment = models.FileField(
        "biriktirilgan fayl", upload_to="homework/tasks/%Y/%m/", blank=True,
        validators=[FileExtensionValidator(HOMEWORK_EXTENSIONS), validate_homework_file],
    )
    due_at = models.DateTimeField("topshirish muddati")
    teacher = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="o‘qituvchi", on_delete=models.PROTECT, related_name="homeworks")
    created_at = models.DateTimeField("yaratilgan vaqt", auto_now_add=True)

    class Meta:
        ordering = ["-due_at"]
        verbose_name = "uyga vazifa"
        verbose_name_plural = "Uyga vazifalar"

    def clean(self):
        if self.lesson_id and self.group_id and self.lesson.group_id != self.group_id:
            raise ValidationError({"lesson": "Dars tanlangan guruhga tegishli emas."})

    @property
    def is_past_due(self):
        return self.due_at < timezone.now()

    def __str__(self):
        return f"{self.title} — {self.group}"


class HomeworkSubmission(models.Model):
    homework = models.ForeignKey(Homework, verbose_name="vazifa", on_delete=models.CASCADE, related_name="submissions")
    student = models.ForeignKey(StudentProfile, verbose_name="o‘quvchi", on_delete=models.CASCADE, related_name="homework_submissions")
    text = models.TextField("javob matni", blank=True, max_length=4000)
    file = models.FileField(
        "fayl", upload_to="homework/answers/%Y/%m/", blank=True,
        validators=[FileExtensionValidator(HOMEWORK_EXTENSIONS), validate_homework_file],
    )
    submitted_at = models.DateTimeField("topshirilgan vaqt", auto_now=True)
    is_late = models.BooleanField("kechikib topshirilgan", default=False)
    score = models.PositiveSmallIntegerField("baho", null=True, blank=True)
    feedback = models.TextField("o‘qituvchi izohi", blank=True, max_length=2000)
    graded_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="baholagan", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    graded_at = models.DateTimeField("baholangan vaqt", null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["homework", "student"], name="one_submission_per_student_per_homework"),
            models.CheckConstraint(condition=Q(score__isnull=True) | (Q(score__gte=0) & Q(score__lte=10)), name="submission_score_0_to_10"),
        ]
        ordering = ["student__user__last_name", "student__user__first_name"]
        verbose_name = "vazifa javobi"
        verbose_name_plural = "Vazifa javoblari"

    def clean(self):
        if self.homework_id and self.student_id and self.homework.group_id != self.student.group_id:
            raise ValidationError("O‘quvchi ushbu vazifa guruhiga tegishli emas.")

    def __str__(self):
        return f"{self.student} — {self.homework}"



class Course(models.Model):
    """Ochiq saytda ko‘rsatiladigan kurs (admin paneldan boshqariladi)."""

    title = models.CharField("nomi", max_length=120)
    slug = models.SlugField("havola nomi", max_length=140, unique=True, allow_unicode=False)
    summary = models.CharField("qisqa tavsif", max_length=240)
    description = models.TextField("batafsil tavsif", blank=True, max_length=5000)
    price = models.DecimalField("oylik narx (so‘m)", max_digits=12, decimal_places=2)
    duration = models.CharField("davomiyligi", max_length=80, blank=True, help_text="Masalan: 6 oy, haftasiga 3 marta")
    is_published = models.BooleanField("saytda ko‘rsatilsin", default=True)
    order = models.PositiveSmallIntegerField("tartib", default=0)
    updated_at = models.DateTimeField("yangilangan vaqt", auto_now=True)

    class Meta:
        ordering = ["order", "title"]
        verbose_name = "kurs"
        verbose_name_plural = "Kurslar"

    def __str__(self):
        return self.title


class EnrollmentApplication(models.Model):
    class Status(models.TextChoices):
        NEW = "new", "Yangi"
        CONTACTED = "contacted", "Bog‘lanildi"
        ENROLLED = "enrolled", "Qabul qilindi"
        REJECTED = "rejected", "Rad etildi"

    full_name = models.CharField("ism-familiya", max_length=120)
    phone = models.CharField("telefon", max_length=24)
    course = models.ForeignKey(Course, verbose_name="kurs", on_delete=models.SET_NULL, null=True, blank=True, related_name="applications")
    message = models.CharField("izoh", max_length=500, blank=True)
    status = models.CharField("holati", max_length=10, choices=Status.choices, default=Status.NEW)
    ip_digest = models.CharField(max_length=64, blank=True, db_index=True)
    created_at = models.DateTimeField("yuborilgan vaqt", auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "ro‘yxatdan o‘tish arizasi"
        verbose_name_plural = "Arizalar"

    def __str__(self):
        return f"{self.full_name} — {self.phone}"



class TwoFactorDevice(models.Model):
    """Foydalanuvchi uchun ixtiyoriy TOTP (Google Authenticator va shu kabi ilovalar) qurilmasi."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, verbose_name="foydalanuvchi", on_delete=models.CASCADE, related_name="two_factor")
    secret = models.CharField("maxfiy kalit", max_length=64)
    confirmed = models.BooleanField("tasdiqlangan", default=False)
    last_counter = models.BigIntegerField("oxirgi ishlatilgan vaqt oynasi", default=0)
    backup_code_hashes = models.JSONField("zaxira kodlar (xesh)", default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "2FA qurilmasi"
        verbose_name_plural = "2FA qurilmalari"

    def __str__(self):
        return f"2FA: {self.user_id}"


class AuditLog(models.Model):
    class Action(models.TextChoices):
        CREATE = "create", "Yaratildi"
        UPDATE = "update", "O‘zgartirildi"
        DELETE = "delete", "O‘chirildi"
        LOGIN = "login", "Kirdi"
        LOGOUT = "logout", "Chiqdi"
        LOGIN_FAILED = "login_failed", "Kirish muvaffaqiyatsiz"
        TWO_FACTOR = "two_factor", "2FA"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="foydalanuvchi", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    username = models.CharField("login", max_length=150, blank=True)
    action = models.CharField("amal", max_length=14, choices=Action.choices)
    model = models.CharField("model", max_length=80, blank=True)
    object_id = models.CharField("obyekt ID", max_length=40, blank=True)
    object_repr = models.CharField("obyekt", max_length=200, blank=True)
    changes = models.JSONField("o‘zgarishlar", default=dict, blank=True)
    ip_address = models.GenericIPAddressField("IP manzil", null=True, blank=True)
    created_at = models.DateTimeField("vaqt", auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "o‘zgarishlar jurnali"
        verbose_name_plural = "O‘zgarishlar jurnali"

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.username} {self.action} {self.model}"
