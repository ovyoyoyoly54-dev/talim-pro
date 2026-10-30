from django import forms
from django.core.exceptions import ValidationError
from django.contrib.auth.password_validation import validate_password
from .models import GradeRecord, GradeReason, Attendance, Lesson, StudentProfile
from .phone_auth import normalize_phone

class GradeRecordForm(forms.Form):
    lesson = forms.ModelChoiceField(queryset=Lesson.objects.none(), widget=forms.Select(attrs={"class": "input"}))
    student = forms.ModelChoiceField(queryset=StudentProfile.objects.none(), widget=forms.Select(attrs={"class": "input"}))
    score = forms.IntegerField(min_value=0, max_value=10, widget=forms.NumberInput(attrs={"class": "input", "min": 0, "max": 10}))
    reasons = forms.ModelMultipleChoiceField(
        queryset=GradeReason.objects.filter(active=True), required=False,
        widget=forms.CheckboxSelectMultiple(attrs={"class": "reason-checkbox"})
    )
    note = forms.CharField(required=False, max_length=1000, widget=forms.Textarea(attrs={"class": "input", "rows": 3, "placeholder": "Qo‘shimcha izoh..."}))
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
        if score is not None and score < 8 and not reasons:
            self.add_error("reasons", "8 dan past baho uchun kamida bitta sabab tanlanishi shart.")
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


class PhoneOTPForm(forms.Form):
    code = forms.CharField(min_length=6, max_length=6, widget=forms.TextInput(attrs={"class": "input", "inputmode": "numeric", "autocomplete": "one-time-code", "pattern": "[0-9]{6}", "placeholder": "000000"}))

    def clean_code(self):
        code = self.cleaned_data["code"]
        if not code.isdigit():
            raise ValidationError("Tasdiqlash kodi 6 ta raqamdan iborat bo‘lishi kerak.")
        return code


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
