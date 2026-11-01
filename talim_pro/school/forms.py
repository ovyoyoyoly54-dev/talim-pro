from django import forms
from django.core.exceptions import ValidationError
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.forms import PasswordChangeForm
from django.utils import timezone
from .models import GradeRecord, GradeReason, Attendance, Lesson, StudentProfile, StudyGroup, User, PlatformSettings
from .phone_auth import normalize_phone


class PlatformSettingsForm(forms.ModelForm):
    class Meta:
        model = PlatformSettings
        fields = ("site_name", "home_heading", "home_description", "contact_phone", "contact_email")
        widgets = {
            "site_name": forms.TextInput(attrs={"class": "input"}),
            "home_heading": forms.TextInput(attrs={"class": "input"}),
            "home_description": forms.Textarea(attrs={"class": "input", "rows": 3}),
            "contact_phone": forms.TextInput(attrs={"class": "input", "type": "tel"}),
            "contact_email": forms.EmailInput(attrs={"class": "input"}),
        }


class AccountSettingsForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("username", "first_name", "last_name", "email", "phone")
        labels = {
            "username": "Foydalanuvchi nomi",
            "first_name": "Ism",
            "last_name": "Familiya",
            "email": "Email",
            "phone": "Telefon raqami",
        }
        widgets = {
            "username": forms.TextInput(attrs={"class": "input", "autocomplete": "username"}),
            "first_name": forms.TextInput(attrs={"class": "input", "autocomplete": "given-name"}),
            "last_name": forms.TextInput(attrs={"class": "input", "autocomplete": "family-name"}),
            "email": forms.EmailInput(attrs={"class": "input", "autocomplete": "email"}),
            "phone": forms.TextInput(attrs={"class": "input", "type": "tel", "autocomplete": "tel", "placeholder": "+998 90 123 45 67"}),
        }


AdminAccountSettingsForm = AccountSettingsForm


class StyledPasswordChangeForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.widget.attrs["class"] = "input"
            field.widget.attrs["autocomplete"] = "current-password" if name == "old_password" else "new-password"

class LessonCreateForm(forms.ModelForm):
    starts_at = forms.DateTimeField(
        label="Sana va vaqt",
        input_formats=["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"],
        widget=forms.DateTimeInput(
            format="%Y-%m-%dT%H:%M",
            attrs={"class": "input", "type": "datetime-local"},
        ),
        help_text="Dars boshlanish sanasi va vaqtini tanlang.",
    )

    class Meta:
        model = Lesson
        fields = ("title", "group", "teacher", "starts_at", "room")
        labels = {
            "title": "Dars mavzusi",
            "group": "O‘quv guruhi",
            "teacher": "O‘qituvchi",
            "room": "Xona",
        }
        widgets = {
            "title": forms.TextInput(attrs={"class": "input", "placeholder": "Masalan: Present Simple", "autocomplete": "off"}),
            "group": forms.Select(attrs={"class": "input"}),
            "teacher": forms.Select(attrs={"class": "input"}),
            "room": forms.TextInput(attrs={"class": "input", "placeholder": "Masalan: 201-xona", "autocomplete": "off"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["group"].queryset = StudyGroup.objects.order_by("name")
        self.fields["teacher"].queryset = User.objects.filter(
            role=User.Role.TEACHER, is_active=True,
        ).order_by("last_name", "first_name", "username")
        self.fields["starts_at"].widget.attrs["min"] = timezone.localtime().strftime("%Y-%m-%dT%H:%M")

    def clean_title(self):
        title = self.cleaned_data["title"].strip()
        if not title:
            raise ValidationError("Dars mavzusini kiriting.")
        return title

    def clean_room(self):
        return self.cleaned_data["room"].strip()

    def clean(self):
        data = super().clean()
        starts_at = data.get("starts_at")
        if starts_at and starts_at <= timezone.now():
            self.add_error("starts_at", "Dars vaqti kelajakda bo‘lishi kerak.")
        return data


class LessonRescheduleForm(forms.Form):
    starts_at = forms.DateTimeField(
        label="Yangi sana va vaqt",
        input_formats=["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"],
        widget=forms.DateTimeInput(
            format="%Y-%m-%dT%H:%M",
            attrs={"class": "input", "type": "datetime-local"},
        ),
        help_text="Dars boshlanishining yangi sana va vaqtini tanlang.",
    )

    def __init__(self, *args, lesson=None, **kwargs):
        super().__init__(*args, **kwargs)
        if lesson and not self.is_bound:
            self.initial["starts_at"] = timezone.localtime(lesson.starts_at)
        self.fields["starts_at"].widget.attrs["min"] = timezone.localtime().strftime("%Y-%m-%dT%H:%M")

    def clean_starts_at(self):
        starts_at = self.cleaned_data["starts_at"]
        if starts_at <= timezone.now():
            raise ValidationError("Dars vaqti kelajakda bo‘lishi kerak.")
        return starts_at


class GradeRecordForm(forms.Form):
    lesson = forms.ModelChoiceField(queryset=Lesson.objects.none(), widget=forms.Select(attrs={"class": "input"}))
    student = forms.ModelChoiceField(queryset=StudentProfile.objects.none(), widget=forms.Select(attrs={"class": "input"}))
    score = forms.IntegerField(min_value=0, max_value=10, widget=forms.NumberInput(attrs={"class": "input", "min": 0, "max": 10}))
    reasons = forms.ModelMultipleChoiceField(
        queryset=GradeReason.objects.filter(active=True), required=False,
        widget=forms.CheckboxSelectMultiple(attrs={"class": "reason-checkbox"})
    )
    attendance = forms.ChoiceField(choices=Attendance.Status.choices, widget=forms.RadioSelect)

    def __init__(self, *args, teacher=None, **kwargs):
        super().__init__(*args, **kwargs)
        if teacher:
            allowed = Lesson.objects.filter(group__teachers=teacher, teacher=teacher)
            self.fields["lesson"].queryset = allowed
            self.fields["student"].queryset = StudentProfile.objects.filter(group__in=allowed.values("group_id"))
    def clean(self):
        data = super().clean()
        score = data.get("score")
        reasons = data.get("reasons")
        lesson = data.get("lesson")
        student = data.get("student")
        if score is not None and score <= 8 and not reasons:
            self.add_error("reasons", "8 yoki undan past baho uchun kamida bitta sabab tanlang.")
        if lesson and student and lesson.group_id != student.group_id:
            raise ValidationError("O‘quvchi tanlangan dars guruhida emas.")
        return data


class PhoneResetRequestForm(forms.Form):
    username = forms.CharField(max_length=150, widget=forms.TextInput(attrs={"class": "input", "autocomplete": "username"}))
    phone = forms.CharField(max_length=24, widget=forms.TextInput(attrs={"class": "input", "type": "tel", "autocomplete": "tel", "placeholder": "+998 90 123 45 67"}))

    def clean_phone(self):
        phone = normalize_phone(self.cleaned_data["phone"])
        if not phone:
            raise ValidationError("Telefon raqamini xalqaro formatda kiriting.")
        return phone


class SignupRequestForm(forms.Form):
    username = forms.CharField(max_length=150, label="Foydalanuvchi nomi", widget=forms.TextInput(attrs={"class": "input", "autocomplete": "username"}))
    first_name = forms.CharField(max_length=150, label="Ism", widget=forms.TextInput(attrs={"class": "input", "autocomplete": "given-name"}))
    last_name = forms.CharField(max_length=150, label="Familiya", widget=forms.TextInput(attrs={"class": "input", "autocomplete": "family-name"}))
    phone = forms.CharField(max_length=24, label="Telefon raqami", widget=forms.TextInput(attrs={"class": "input", "type": "tel", "autocomplete": "tel", "placeholder": "+998 90 123 45 67"}))
    group = forms.ModelChoiceField(queryset=StudyGroup.objects.none(), label="O‘quv guruhi", widget=forms.Select(attrs={"class": "input"}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["group"].queryset = StudyGroup.objects.all()

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if User.objects.filter(username__iexact=username).exists():
            raise ValidationError("Bu foydalanuvchi nomi band. Boshqasini tanlang.")
        return username

    def clean_phone(self):
        phone = normalize_phone(self.cleaned_data["phone"])
        if not phone:
            raise ValidationError("Telefon raqamini xalqaro formatda kiriting.")
        return phone


class PhoneOTPForm(forms.Form):
    code = forms.CharField(min_length=6, max_length=6, widget=forms.TextInput(attrs={"class": "input", "inputmode": "numeric", "autocomplete": "one-time-code", "pattern": "[0-9]{6}", "placeholder": "000000"}))

    def clean_code(self):
        code = self.cleaned_data["code"]
        if not code.isdigit():
            raise ValidationError("Tasdiqlash kodi 6 ta raqamdan iborat bo‘lishi kerak.")
        return code


class AccountClosureConfirmForm(forms.Form):
    username = forms.CharField(
        label="Login",
        widget=forms.TextInput(attrs={"class": "input", "autocomplete": "username"}),
    )
    password = forms.CharField(
        label="Joriy parol",
        widget=forms.PasswordInput(attrs={"class": "input", "autocomplete": "current-password"}),
    )

    def __init__(self, *args, user, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.initial["username"] = user.get_username()

    def clean_username(self):
        username = self.cleaned_data["username"]
        if username != self.user.get_username():
            raise ValidationError("Login noto‘g‘ri.")
        return username

    def clean_password(self):
        password = self.cleaned_data["password"]
        if not self.user.check_password(password):
            raise ValidationError("Login parolingiz noto‘g‘ri.")
        return password


class SignupCompleteForm(PhoneOTPForm):
    new_password = forms.CharField(min_length=8, label="Parol", widget=forms.PasswordInput(attrs={"class": "input", "autocomplete": "new-password"}))
    confirm_password = forms.CharField(label="Parolni takrorlang", widget=forms.PasswordInput(attrs={"class": "input", "autocomplete": "new-password"}))

    def clean(self):
        data = super().clean()
        password = data.get("new_password")
        if password:
            try:
                validate_password(password)
            except ValidationError as exc:
                self.add_error("new_password", exc)
        if password and data.get("confirm_password") and password != data["confirm_password"]:
            self.add_error("confirm_password", "Parollar bir xil emas.")
        return data


class PhonePasswordResetForm(PhoneOTPForm):
    new_password = forms.CharField(min_length=8, widget=forms.PasswordInput(attrs={"class": "input", "autocomplete": "new-password"}), label="Yangi parol")
    confirm_password = forms.CharField(widget=forms.PasswordInput(attrs={"class": "input", "autocomplete": "new-password"}), label="Yangi parolni takrorlang")

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean(self):
        data = super().clean()
        password = data.get("new_password")
        if password and self.user:
            try:
                validate_password(password, self.user)
            except ValidationError as exc:
                self.add_error("new_password", exc)
        if password and data.get("confirm_password") and password != data["confirm_password"]:
            self.add_error("confirm_password", "Parollar bir xil emas.")
        return data


class AddStudentToGroupForm(forms.Form):
    """O'quvchini guruhga qo'shish forme. Faqat hali hech bir guruhga biriktirilmagan
    STUDENT rolldagi foydalanuvchilarni ko'rsatadi."""
    student = forms.ModelChoiceField(
        queryset=User.objects.none(),
        widget=forms.Select(attrs={"class": "input"}),
        label="O'quvchi",
    )
    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "input", "placeholder": "Ism yoki familiay bo'yicha qidirish...", "autocomplete": "off"}),
        label="Qidirish",
    )

    def __init__(self, *args, teacher=None, group=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.teacher = teacher
        self.group = group
        # Faqat STUDENT ro'li va hali StudentProfile'i yo'q foydalanuvchilar
        queryset = User.objects.filter(
            role=User.Role.STUDENT,
            is_active=True,
            student_profile__isnull=True,
        ).order_by("last_name", "first_name", "username")
        self.fields["student"].queryset = queryset

    def clean_student(self):
        student = self.cleaned_data.get("student")
        if not student:
            raise ValidationError("O'quvchini tanlang.")
        # Server tomondan ro'yxatdan o'tganligini tekshirish
        if student.role != User.Role.STUDENT or not student.is_active:
            raise ValidationError("Faqat faol o'quvchi hisobini guruhga qo'shish mumkin.")
        # Allaqachon guruhga biriktirilganligini tekshirish
        if hasattr(student, "student_profile") and student.student_profile_id:
            raise ValidationError("Ushbu foydalanuvchi allaqachon boshqa guruhga biriktirilgan.")
        # Ko'paytma qo'shishni bloklash (bu guruhda allaqachon bo'lsa)
        if self.group and self.group.students.filter(user_id=student.pk).exists():
            raise ValidationError("Ushbu o'quvchi allaqachon sizning guruhingizda bor.")
        return student


class CreateStudentInGroupForm(forms.Form):
    first_name = forms.CharField(max_length=150, label="O‘quvchi ismi", widget=forms.TextInput(attrs={"class": "input", "autocomplete": "given-name"}))
    last_name = forms.CharField(max_length=150, label="O‘quvchi familiyasi", widget=forms.TextInput(attrs={"class": "input", "autocomplete": "family-name"}))
    parent_phone = forms.CharField(required=False, max_length=24, label="Ota-onaning SMS raqami", widget=forms.TextInput(attrs={"class": "input", "type": "tel", "placeholder": "+998 90 123 45 67"}))

    def clean_first_name(self):
        value = self.cleaned_data["first_name"].strip()
        if not value:
            raise ValidationError("O‘quvchi ismini kiriting.")
        return value

    def clean_last_name(self):
        value = self.cleaned_data["last_name"].strip()
        if not value:
            raise ValidationError("O‘quvchi familiyasini kiriting.")
        return value

    def clean_parent_phone(self):
        value = self.cleaned_data.get("parent_phone", "").strip()
        if not value:
            return ""
        phone = normalize_phone(value)
        if not phone:
            raise ValidationError("Ota-ona telefon raqamini +998 formatida kiriting.")
        return phone


class CreateTeacherForm(forms.Form):
    first_name = forms.CharField(max_length=150, label="Ismi", widget=forms.TextInput(attrs={"class": "input", "autocomplete": "given-name"}))
    last_name = forms.CharField(max_length=150, label="Familiyasi", widget=forms.TextInput(attrs={"class": "input", "autocomplete": "family-name"}))
    phone = forms.CharField(required=False, max_length=24, label="Telefon raqami", widget=forms.TextInput(attrs={"class": "input", "type": "tel", "placeholder": "+998 90 123 45 67"}))

    def clean_first_name(self):
        value = self.cleaned_data["first_name"].strip()
        if not value:
            raise ValidationError("O‘qituvchi ismini kiriting.")
        return value

    def clean_last_name(self):
        value = self.cleaned_data["last_name"].strip()
        if not value:
            raise ValidationError("O‘qituvchi familiyasini kiriting.")
        return value

    def clean_phone(self):
        value = self.cleaned_data.get("phone", "").strip()
        if not value:
            return ""
        phone = normalize_phone(value)
        if not phone:
            raise ValidationError("Telefon raqamini +998 formatida kiriting.")
        return phone
