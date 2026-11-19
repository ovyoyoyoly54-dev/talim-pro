from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.utils.translation import gettext as _

from .models import Homework, HomeworkSubmission, StudentProfile, StudyGroup, User
from .notifications import notify
from .views import is_admin, posted_object_or_404


class HomeworkForm(forms.ModelForm):
    due_at = forms.DateTimeField(
        label="Topshirish muddati", input_formats=["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"],
        widget=forms.DateTimeInput(attrs={"class": "input", "type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
    )

    class Meta:
        model = Homework
        fields = ("group", "title", "description", "attachment", "due_at")
        widgets = {
            "group": forms.Select(attrs={"class": "input"}),
            "title": forms.TextInput(attrs={"class": "input"}),
            "description": forms.Textarea(attrs={"class": "input", "rows": 5}),
            "attachment": forms.ClearableFileInput(attrs={"class": "input"}),
        }

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        groups = StudyGroup.objects.all() if is_admin(user) else StudyGroup.objects.filter(teachers=user)
        self.fields["group"].queryset = groups

    def clean_due_at(self):
        due = self.cleaned_data["due_at"]
        if due <= timezone.now():
            raise forms.ValidationError("Muddat kelajakda bo‘lishi kerak.")
        return due


class SubmissionForm(forms.ModelForm):
    class Meta:
        model = HomeworkSubmission
        fields = ("text", "file")
        widgets = {
            "text": forms.Textarea(attrs={"class": "input", "rows": 5}),
            "file": forms.ClearableFileInput(attrs={"class": "input"}),
        }

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("text", "").strip() and not cleaned.get("file") and not (self.instance.pk and self.instance.file):
            raise forms.ValidationError("Javob matni yoki fayl kiriting.")
        return cleaned


class GradeForm(forms.Form):
    score = forms.IntegerField(min_value=0, max_value=10, widget=forms.NumberInput(attrs={"class": "input", "min": 0, "max": 10}))
    feedback = forms.CharField(required=False, max_length=2000, widget=forms.Textarea(attrs={"class": "input", "rows": 2}))


def _can_manage(user, homework):
    if is_admin(user):
        return True
    return user.role == User.Role.TEACHER and homework.group.teachers.filter(pk=user.pk).exists()


def _student_profile(user):
    return StudentProfile.objects.filter(user=user).select_related("group").first()


def _visible_homework(user):
    qs = Homework.objects.select_related("group", "teacher")
    if is_admin(user):
        return qs
    if user.role == User.Role.TEACHER:
        return qs.filter(group__teachers=user)
    if user.role == User.Role.STUDENT:
        return qs.filter(group__students__user=user)
    if user.role == User.Role.PARENT:
        return qs.filter(group__students__parent=user).distinct()
    raise PermissionDenied


def _teacher_groups(user):
    """Faqat o‘qituvchi uchun: u dars beradigan guruhlar (administrator va boshqalar uchun None)."""
    if is_admin(user) or user.role != User.Role.TEACHER:
        return None
    return list(StudyGroup.objects.filter(teachers=user).order_by("name"))


@login_required
def homework_list(request):
    groups = _teacher_groups(request.user)
    queryset = _visible_homework(request.user)
    selected = None
    if groups is not None and len(groups) > 1:
        # Bir nechta sinfga dars beradigan o‘qituvchidan avval qaysi sinf ekanini so‘raymiz.
        group_id = request.GET.get("group", "")
        selected = next((g for g in groups if str(g.pk) == group_id), None)
        if selected is None:
            return render(request, "school/homework_group_picker.html", {"groups": groups})
        queryset = queryset.filter(group=selected)
    elif groups:
        selected = groups[0]
    items = list(queryset.order_by("-due_at")[:100])
    submitted = {}
    if request.user.role == User.Role.STUDENT:
        profile = _student_profile(request.user)
        if profile:
            submitted = {s.homework_id: s for s in HomeworkSubmission.objects.filter(student=profile)}
    for item in items:
        item.my_submission = submitted.get(item.pk)
    return render(request, "school/homework_list.html", {
        "items": items, "can_create": is_admin(request.user) or request.user.role == User.Role.TEACHER,
        "selected_group": selected, "switch_group": bool(groups and len(groups) > 1),
    })


@login_required
def homework_create(request):
    user = request.user
    if not (is_admin(user) or user.role == User.Role.TEACHER):
        raise PermissionDenied
    initial = {}
    preset = request.GET.get("group", "")
    if preset.isdigit():
        initial["group"] = int(preset)
    form = HomeworkForm(request.POST or None, request.FILES or None, user=user, initial=initial)
    if request.method == "POST" and form.is_valid():
        homework = form.save(commit=False)
        homework.teacher = user
        homework.save()
        students = [p.user for p in StudentProfile.objects.filter(group=homework.group, user__is_active=True).select_related("user")]
        parents = [p.parent for p in StudentProfile.objects.filter(group=homework.group, parent__isnull=False).select_related("parent")]
        notify(students + parents, _("Yangi uyga vazifa"),
               _("%(title)s — muddat: %(due)s") % {"title": homework.title, "due": timezone.localtime(homework.due_at).strftime("%d.%m.%Y %H:%M")},
               f"/vazifalar/{homework.pk}/")
        messages.success(request, _("Uyga vazifa yaratildi."))
        return redirect("homework_detail", homework_id=homework.pk)
    return render(request, "school/homework_form.html", {"form": form})


@login_required
def homework_detail(request, homework_id):
    user = request.user
    homework = get_object_or_404(_visible_homework(user), pk=homework_id)
    manage = _can_manage(user, homework)
    context = {"homework": homework, "manage": manage}

    if manage:
        if request.method == "POST" and request.POST.get("action") == "grade":
            submission = posted_object_or_404(homework.submissions.all(), request.POST.get("submission_id"))
            form = GradeForm(request.POST)
            if form.is_valid():
                submission.score = form.cleaned_data["score"]
                submission.feedback = form.cleaned_data["feedback"]
                submission.graded_by = user
                submission.graded_at = timezone.now()
                submission.save(update_fields=["score", "feedback", "graded_by", "graded_at"])
                from .notifications import notify_family
                notify_family(submission.student, _("Uyga vazifa baholandi"),
                              _("%(title)s: %(score)s/10") % {"title": homework.title, "score": submission.score},
                              f"/vazifalar/{homework.pk}/")
                messages.success(request, _("Baho saqlandi."))
            else:
                messages.error(request, _("Baho 0 dan 10 gacha butun son bo‘lishi kerak."))
            return redirect("homework_detail", homework_id=homework.pk)
        students = StudentProfile.objects.filter(
            group=homework.group, user__role=User.Role.STUDENT, user__is_active=True,
        ).select_related("user").order_by("user__last_name", "user__first_name")
        subs = {s.student_id: s for s in homework.submissions.all()}
        context["rows"] = [{"student": st, "submission": subs.get(st.pk)} for st in students]
        return render(request, "school/homework_detail.html", context)

    if user.role == User.Role.STUDENT:
        profile = _student_profile(user)
        submission = HomeworkSubmission.objects.filter(homework=homework, student=profile).first() if profile else None
        form = SubmissionForm(request.POST or None, request.FILES or None, instance=submission)
        if request.method == "POST":
            if profile is None or profile.group_id != homework.group_id:
                raise PermissionDenied
            if submission and submission.score is not None:
                messages.error(request, _("Baholangan vazifani qayta topshirib bo‘lmaydi."))
                return redirect("homework_detail", homework_id=homework.pk)
            if form.is_valid():
                sub = form.save(commit=False)
                sub.homework, sub.student = homework, profile
                sub.is_late = homework.is_past_due
                sub.save()
                notify(homework.group.teachers.all(), _("Vazifa topshirildi"),
                       f"{user.get_full_name() or user.username}: {homework.title}", f"/vazifalar/{homework.pk}/")
                messages.success(request, _("Javobingiz saqlandi."))
                return redirect("homework_detail", homework_id=homework.pk)
        context.update({"form": form, "submission": submission})
    else:  # ota-ona: farzandlarining javoblarini ko‘radi
        context["children_subs"] = HomeworkSubmission.objects.filter(
            homework=homework, student__parent=user).select_related("student__user")
    return render(request, "school/homework_detail.html", context)


def _send_file(field):
    if not field:
        raise Http404
    try:
        handle = field.open("rb")
    except (FileNotFoundError, ValueError):
        raise Http404
    response = FileResponse(handle, as_attachment=True, filename=field.name.rsplit("/", 1)[-1])
    response["X-Content-Type-Options"] = "nosniff"
    return response


@login_required
def homework_task_file(request, homework_id):
    homework = get_object_or_404(_visible_homework(request.user), pk=homework_id)
    return _send_file(homework.attachment)


@login_required
def homework_answer_file(request, submission_id):
    user = request.user
    submission = get_object_or_404(HomeworkSubmission.objects.select_related("homework__group", "student"), pk=submission_id)
    allowed = (
        _can_manage(user, submission.homework)
        or submission.student.user_id == user.pk
        or (user.role == User.Role.PARENT and submission.student.parent_id == user.pk)
    )
    if not allowed:
        raise PermissionDenied
    return _send_file(submission.file)
