from django import forms
from django.core.exceptions import ValidationError
from .models import GradeRecord, GradeReason, Attendance, Lesson, StudentProfile

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
