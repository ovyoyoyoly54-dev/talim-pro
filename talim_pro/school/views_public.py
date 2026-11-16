import hashlib
import hmac
from datetime import timedelta

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_POST

from .models import Course, EnrollmentApplication, User
from .notifications import notify
from .phone_auth import normalize_phone
from .utils import get_client_ip
from .views import is_admin

APPLICATIONS_PER_HOUR = 5


def _canonical(request):
    return settings.PUBLIC_SITE_URL or request.build_absolute_uri("/").rstrip("/")


class ApplicationForm(forms.ModelForm):
    # Botlar to‘ldiradigan yashirin maydon: odam ko‘rmaydi, shuning uchun bo‘sh qoladi.
    website = forms.CharField(required=False, widget=forms.TextInput(attrs={"tabindex": "-1", "autocomplete": "off"}))

    class Meta:
        model = EnrollmentApplication
        fields = ("full_name", "phone", "course", "message")
        widgets = {
            "full_name": forms.TextInput(attrs={"class": "input", "autocomplete": "name"}),
            "phone": forms.TextInput(attrs={"class": "input", "type": "tel", "autocomplete": "tel", "placeholder": "+998 90 123 45 67"}),
            "course": forms.Select(attrs={"class": "input"}),
            "message": forms.TextInput(attrs={"class": "input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["course"].queryset = Course.objects.filter(is_published=True)
        self.fields["course"].required = False
        self.fields["course"].empty_label = "—"

    def clean_phone(self):
        phone = normalize_phone(self.cleaned_data["phone"])
        if not phone:
            raise forms.ValidationError("Telefon raqamini +998 formatida kiriting.")
        return phone

    def clean_website(self):
        if self.cleaned_data.get("website"):
            raise forms.ValidationError("Spam aniqlandi.")
        return ""


@require_GET
def courses_list(request):
    return render(request, "school/courses.html", {
        "courses": Course.objects.filter(is_published=True), "canonical_url": _canonical(request) + request.path,
    })


@require_GET
def course_detail(request, slug):
    course = get_object_or_404(Course, slug=slug, is_published=True)
    return render(request, "school/course_detail.html", {
        "course": course, "canonical_url": _canonical(request) + request.path,
    })


@require_GET
def pricing(request):
    return render(request, "school/pricing.html", {
        "courses": Course.objects.filter(is_published=True), "canonical_url": _canonical(request) + request.path,
    })


def apply(request):
    initial = {}
    slug = request.GET.get("kurs")
    if slug:
        course = Course.objects.filter(slug=slug, is_published=True).first()
        if course:
            initial["course"] = course
    form = ApplicationForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        digest = hmac.new(settings.SECRET_KEY.encode(), get_client_ip(request).encode(), hashlib.sha256).hexdigest()
        recent = EnrollmentApplication.objects.filter(
            ip_digest=digest, created_at__gte=timezone.now() - timedelta(hours=1)).count()
        if recent >= APPLICATIONS_PER_HOUR:
            form.add_error(None, "Juda ko‘p ariza yuborildi. Birozdan keyin qayta urinib ko‘ring.")
        else:
            application = form.save(commit=False)
            application.ip_digest = digest
            application.save()
            notify(User.objects.filter(is_active=True, role=User.Role.ADMIN), _("Yangi ariza"),
                   f"{application.full_name}, {application.phone}", "/arizalar/")
            return redirect("apply_done")
    return render(request, "school/apply.html", {"form": form, "canonical_url": _canonical(request) + request.path})


@require_GET
def apply_done(request):
    return render(request, "school/apply_done.html")


@login_required
def applications_list(request):
    if not is_admin(request.user):
        raise PermissionDenied
    if request.method == "POST":
        application = get_object_or_404(EnrollmentApplication, pk=request.POST.get("application_id"))
        status = request.POST.get("status")
        if status in EnrollmentApplication.Status.values:
            application.status = status
            application.save(update_fields=["status"])
            messages.success(request, _("Ariza holati yangilandi."))
        return redirect("applications_list")
    status = request.GET.get("status", "")
    items = EnrollmentApplication.objects.select_related("course")
    if status in EnrollmentApplication.Status.values:
        items = items.filter(status=status)
    return render(request, "school/applications.html", {
        "items": items[:200], "statuses": EnrollmentApplication.Status.choices, "status": status,
    })
