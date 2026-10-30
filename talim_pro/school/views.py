from django.contrib import messages
from django.contrib.auth import logout, login as auth_login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Avg, Sum, Count
from django.shortcuts import render, redirect, get_object_or_404
from django.http import FileResponse, JsonResponse, HttpResponse
from django.conf import settings
from django.templatetags.static import static
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET
from xml.sax.saxutils import escape
from .forms import GradeRecordForm, PhoneResetRequestForm, PhoneOTPForm, PhonePasswordResetForm, SignupRequestForm, SignupCompleteForm
from .models import User, StudyGroup, StudentProfile, Lesson, GradeRecord, Attendance, SMSLog, PhoneOTP
from .phone_auth import consume_phone_otp, issue_phone_otp, normalize_phone
from .sms import send_parent_sms

@require_GET
def public_home(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    canonical_url = settings.PUBLIC_SITE_URL or request.build_absolute_uri("/").rstrip("/")
    return render(request, "school/home.html", {"canonical_url": canonical_url})

@require_GET
def robots_txt(request):
    site_url = settings.PUBLIC_SITE_URL or request.build_absolute_uri("/").rstrip("/")
    body = "\n".join([
        "User-agent: *", "Allow: /", "Disallow: /admin/", "Disallow: /login/",
        "Disallow: /logout/", "Disallow: /dashboard/", "Disallow: /baholash/",
        "Disallow: /jadval/", "Disallow: /reyting/", "Disallow: /oquvchi/",
        "Disallow: /parolni-tiklash/", "Disallow: /akkauntni-yopish/",
        "Disallow: /offline/", "Disallow: /service-worker.js", "Disallow: /manifest.webmanifest",
        f"Sitemap: {site_url}{reverse('sitemap_xml')}", "",
    ])
    return HttpResponse(body, content_type="text/plain; charset=utf-8")

@require_GET
def sitemap_xml(request):
    site_url = settings.PUBLIC_SITE_URL or request.build_absolute_uri("/").rstrip("/")
    location = escape(f"{site_url}{reverse('home')}")
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"<url><loc>{location}</loc></url>"
        "</urlset>"
    )
    return HttpResponse(body, content_type="application/xml; charset=utf-8")

@require_GET
def service_worker(request):
    response = FileResponse(
        (settings.BASE_DIR / "static" / "school" / "service-worker.js").open("rb"),
        content_type="application/javascript",
    )
    response["Service-Worker-Allowed"] = "/"
    response["Cache-Control"] = "no-cache"
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response

@require_GET
def web_manifest(request):
    response = JsonResponse({
        "id": "/", "name": "TA’LIM PRO — O‘quv markazi", "short_name": "TA’LIM PRO",
        "description": "O‘quv jarayonini boshqarish platformasi", "lang": "uz",
        "start_url": "/", "scope": "/", "display": "standalone",
        "orientation": "portrait-primary", "background_color": "#f5f7fb",
        "theme_color": "#102544",
        "icons": [
            {"src": static("school/icon-192.png"), "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
            {"src": static("school/icon-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
            {"src": static("school/icon.svg"), "sizes": "any", "type": "image/svg+xml", "purpose": "any"},
        ],
    }, content_type="application/manifest+json")
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response

@require_GET
def offline_page(request):
    response = FileResponse(
        (settings.BASE_DIR / "static" / "school" / "offline.html").open("rb"),
        content_type="text/html; charset=utf-8",
    )
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response


def signup(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    pending_id = request.session.get("signup_user_id")
    pending_user = User.objects.filter(pk=pending_id, is_active=False).first() if pending_id else None
    challenge_id = request.session.get("signup_otp_id")
    challenge = PhoneOTP.objects.filter(
        pk=challenge_id, user=pending_user, purpose=PhoneOTP.Purpose.SIGNUP,
        consumed_at__isnull=True,
    ).first() if pending_user and challenge_id else None

    if request.method == "POST" and request.POST.get("action") == "send_code":
        if pending_user:
            pending_user.delete()
            for key in ("signup_user_id", "signup_otp_id", "signup_group_id", "signup_started_at"):
                request.session.pop(key, None)
            pending_user = None
            challenge = None
        form = SignupRequestForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            user = User(
                username=data["username"], first_name=data["first_name"], last_name=data["last_name"],
                phone=data["phone"], role=User.Role.STUDENT, is_active=False,
            )
            user.set_unusable_password()
            user.save()
            issued = issue_phone_otp(user=user, purpose=PhoneOTP.Purpose.SIGNUP, request=request)
            if issued:
                request.session["signup_user_id"] = user.pk
                request.session["signup_otp_id"] = issued.pk
                request.session["signup_group_id"] = data["group"].pk
                request.session["signup_started_at"] = timezone.now().timestamp()
                messages.info(request, "Telefoningizga tasdiqlash kodi yuborildi.")
                return redirect("signup")
            user.delete()
            messages.error(request, "SMS kod yuborilmadi. Raqamni tekshiring yoki keyinroq urinib ko‘ring.")
        return render(request, "school/signup.html", {"request_form": form, "has_challenge": bool(challenge)})

    complete_form = SignupCompleteForm()
    if request.method == "POST" and request.POST.get("action") == "complete_signup":
        complete_form = SignupCompleteForm(request.POST)
        started = request.session.get("signup_started_at", 0)
        fresh = timezone.now().timestamp() - started < 3600
        if challenge and pending_user and fresh and complete_form.is_valid():
            if consume_phone_otp(challenge_id=challenge.pk, user=pending_user,
                                 purpose=PhoneOTP.Purpose.SIGNUP, code=complete_form.cleaned_data["code"]):
                group = StudyGroup.objects.filter(pk=request.session.get("signup_group_id")).first()
                if group:
                    with transaction.atomic():
                        pending_user.set_password(complete_form.cleaned_data["new_password"])
                        pending_user.is_active = True
                        pending_user.save(update_fields=["password", "is_active"])
                        StudentProfile.objects.create(user=pending_user, group=group)
                    auth_login(request, pending_user)
                    for key in ("signup_user_id", "signup_otp_id", "signup_group_id", "signup_started_at"):
                        request.session.pop(key, None)
                    return redirect("dashboard")
                complete_form.add_error(None, "Guruh topilmadi. Ro‘yxatdan o‘tishni qaytadan boshlang.")
            else:
                complete_form.add_error("code", "Kod noto‘g‘ri yoki muddati tugagan.")
        elif not challenge or not fresh:
            complete_form.add_error(None, "Tasdiqlash so‘rovi muddati tugagan. Yangi kod so‘rang.")

    return render(request, "school/signup.html", {
        "request_form": SignupRequestForm(), "complete_form": complete_form,
        "has_challenge": bool(challenge),
    })


def password_reset(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    challenge_id = request.session.get("password_reset_otp_id")
    challenge = PhoneOTP.objects.filter(
        pk=challenge_id, purpose=PhoneOTP.Purpose.RESET_PASSWORD, consumed_at__isnull=True
    ).select_related("user").first() if challenge_id else None

    if request.method == "POST" and request.POST.get("action") == "send_code":
        request_form = PhoneResetRequestForm(request.POST)
        if request_form.is_valid():
            username = request_form.cleaned_data["username"]
            phone = request_form.cleaned_data["phone"]
            user = User.objects.filter(username=username, is_active=True).first()
            if user and normalize_phone(user.phone) == phone:
                issued = issue_phone_otp(user=user, purpose=PhoneOTP.Purpose.RESET_PASSWORD, request=request)
                if issued:
                    request.session["password_reset_otp_id"] = issued.pk
            messages.info(request, "Agar login va raqam mos bo‘lsa hamda SMS xizmati ishlasa, tasdiqlash kodi yuboriladi.")
            return redirect("password_reset")
    else:
        request_form = PhoneResetRequestForm()

    otp_form = PhonePasswordResetForm(user=challenge.user if challenge else None)
    if request.method == "POST" and request.POST.get("action") == "reset_password":
        otp_form = PhonePasswordResetForm(request.POST, user=challenge.user if challenge else None)
        if challenge and otp_form.is_valid():
            if consume_phone_otp(
                challenge_id=challenge.pk, user=challenge.user,
                purpose=PhoneOTP.Purpose.RESET_PASSWORD, code=otp_form.cleaned_data["code"],
            ):
                user = challenge.user
                user.set_password(otp_form.cleaned_data["new_password"])
                user.save(update_fields=["password"])
                request.session.pop("password_reset_otp_id", None)
                messages.success(request, "Parol yangilandi. Yangi parol bilan tizimga kiring.")
                return redirect("login")
            if not PhoneOTP.objects.filter(pk=challenge.pk, consumed_at__isnull=True, attempts__lt=5).exists():
                request.session.pop("password_reset_otp_id", None)
            otp_form.add_error("code", "Kod noto‘g‘ri yoki muddati tugagan. Yangi kod so‘rang.")
        elif not challenge:
            otp_form.add_error(None, "Faol tasdiqlash so‘rovi topilmadi. Avval yangi kod so‘rang.")

    return render(request, "school/password_reset.html", {
        "request_form": request_form,
        "otp_form": otp_form,
        "has_challenge": bool(challenge),
    })


@login_required
def close_account(request):
    user = request.user
    if user.is_staff or user.is_superuser or user.role == User.Role.ADMIN:
        raise PermissionDenied("Administrator akkauntini ushbu sahifadan yopib bo‘lmaydi.")

    challenge_id = request.session.get("close_account_otp_id")
    challenge = PhoneOTP.objects.filter(
        pk=challenge_id, user=user, purpose=PhoneOTP.Purpose.CLOSE_ACCOUNT,
        consumed_at__isnull=True,
    ).first() if challenge_id else None

    if request.method == "POST" and request.POST.get("action") == "send_code":
        if not normalize_phone(user.phone):
            messages.error(request, "Akkauntga to‘g‘ri telefon raqami biriktirilmagan. Markaz administratoriga murojaat qiling.")
        else:
            issued = issue_phone_otp(user=user, purpose=PhoneOTP.Purpose.CLOSE_ACCOUNT, request=request)
            if issued:
                request.session["close_account_otp_id"] = issued.pk
                messages.info(request, "Telefon raqamingizga tasdiqlash kodi yuborildi.")
            else:
                messages.error(request, "Kod yuborilmadi. SMS xizmati sozlanganini tekshiring yoki bir daqiqadan keyin qayta urinib ko‘ring.")
        return redirect("close_account")

    otp_form = PhoneOTPForm()
    if request.method == "POST" and request.POST.get("action") == "close_account":
        otp_form = PhoneOTPForm(request.POST)
        if challenge and otp_form.is_valid():
            if consume_phone_otp(
                challenge_id=challenge.pk, user=user,
                purpose=PhoneOTP.Purpose.CLOSE_ACCOUNT, code=otp_form.cleaned_data["code"],
            ):
                # Preserve academic history and foreign-key integrity; disable sign-in only.
                user.is_active = False
                user.save(update_fields=["is_active"])
                request.session.pop("close_account_otp_id", None)
                logout(request)
                messages.success(request, "Akkaunt yopildi. Ta’lim tarixi saqlanadi.")
                return redirect("home")
            if not PhoneOTP.objects.filter(pk=challenge.pk, consumed_at__isnull=True, attempts__lt=5).exists():
                request.session.pop("close_account_otp_id", None)
            otp_form.add_error("code", "Kod noto‘g‘ri yoki muddati tugagan. Yangi kod so‘rang.")
        elif not challenge:
            otp_form.add_error(None, "Faol tasdiqlash so‘rovi topilmadi. Avval yangi kod so‘rang.")

    return render(request, "school/close_account.html", {"otp_form": otp_form, "has_challenge": bool(challenge)})

def is_admin(user): return user.is_authenticated and (user.is_superuser or user.role == User.Role.ADMIN)

def teacher_lessons(user):
    return Lesson.objects.filter(group__teachers=user, teacher=user).select_related("group", "teacher")

@login_required
def dashboard(request):
    user = request.user
    context = {"today": timezone.localdate()}
    if is_admin(user):
        context.update({
            "group_count": StudyGroup.objects.count(),
            "student_count": StudentProfile.objects.count(),
            "lesson_count": Lesson.objects.count(),
            "recent_grades": GradeRecord.objects.select_related("student__user", "lesson").order_by("-updated_at")[:8],
            "groups": StudyGroup.objects.all(),
        })
    elif user.role == User.Role.TEACHER:
        lessons = teacher_lessons(user)
        context.update({"lessons": lessons.filter(starts_at__date__gte=timezone.localdate())[:8],
                        "groups": StudyGroup.objects.filter(teachers=user),
                        "student_count": StudentProfile.objects.filter(group__teachers=user).count(),
                        "recent_grades": GradeRecord.objects.filter(teacher=user).select_related("student__user", "lesson").order_by("-updated_at")[:8]})
    elif user.role == User.Role.STUDENT:
        profile = get_object_or_404(StudentProfile, user=user)
        context.update({"profile": profile, "average_score": profile.grades.aggregate(value=Avg("score"))["value"],
                        "upcoming_lessons": Lesson.objects.filter(group=profile.group, starts_at__gte=timezone.now()).select_related("teacher").order_by("starts_at")[:5],
                        "grades": profile.grades.select_related("lesson").prefetch_related("reasons").order_by("-updated_at")[:10],
                        "attendance_records": profile.attendance.select_related("lesson").order_by("-lesson__starts_at")[:10]})
    elif user.role == User.Role.PARENT:
        children = StudentProfile.objects.filter(parent=user).select_related("user", "group")
        context["children"] = children
    else:
        raise PermissionDenied
    return render(request, "school/dashboard.html", context)

@login_required
def grade_lesson(request):
    if request.user.role != User.Role.TEACHER and not is_admin(request.user):
        raise PermissionDenied
    if request.method == "POST":
        form = GradeRecordForm(request.POST, teacher=request.user if not is_admin(request.user) else None)
        if is_admin(request.user):
            form.fields["lesson"].queryset = Lesson.objects.all()
            form.fields["student"].queryset = StudentProfile.objects.all()
        if form.is_valid():
            lesson, student = form.cleaned_data["lesson"], form.cleaned_data["student"]
            if not is_admin(request.user) and (lesson.teacher_id != request.user.id or not lesson.group.teachers.filter(id=request.user.id).exists()):
                raise PermissionDenied
            if student.group_id != lesson.group_id:
                form.add_error("student", "O‘quvchi tanlangan guruhga tegishli emas.")
            else:
                with transaction.atomic():
                    grade, _ = GradeRecord.objects.get_or_create(
                        lesson=lesson, student=student,
                        defaults={"score": 8, "note": form.cleaned_data["note"], "teacher": request.user}
                    )
                    grade.score = 8
                    grade.note = form.cleaned_data["note"]
                    grade.teacher = request.user
                    grade.save()
                    grade.reasons.set(form.cleaned_data["reasons"])
                    grade.score = form.cleaned_data["score"]
                    grade.save()
                    attendance, _ = Attendance.objects.update_or_create(
                        lesson=lesson, student=student,
                        defaults={"status": form.cleaned_data["attendance"], "teacher": request.user}
                    )
                if grade.score < 8 and student.parent:
                    reason_text = ", ".join(grade.reasons.values_list("title", flat=True))
                    body = (f"Hurmatli ota-ona! {student.user.get_full_name() or student.user.username} "
                            f"{lesson.title} darsidan {grade.score}/10 ball oldi. Sabab: {reason_text or 'ko‘rsatilmagan'}. "
                            f"Davomat: {attendance.get_status_display()}.")
                    log = send_parent_sms(parent=student.parent, student=student, body=body)
                    if log.status == SMSLog.Status.SENT:
                        messages.success(request, "Baho saqlandi va ota-onaga SMS yuborildi.")
                    elif log.status == SMSLog.Status.DISABLED:
                        messages.warning(request, "Baho saqlandi. SMS yuborilmadi: SMS xizmati sozlanmagan.")
                    else:
                        messages.warning(request, "Baho saqlandi, ammo SMS yuborishda xatolik yuz berdi.")
                else:
                    messages.success(request, "Baho va davomat saqlandi.")
                return redirect("dashboard")
    else:
        form = GradeRecordForm(teacher=request.user if not is_admin(request.user) else None)
        if is_admin(request.user):
            form.fields["lesson"].queryset = Lesson.objects.all()
            form.fields["student"].queryset = StudentProfile.objects.all()
    return render(request, "school/grade_form.html", {"form": form})

@login_required
def schedule(request):
    user = request.user
    lessons = Lesson.objects.select_related("group", "teacher")
    if user.role == User.Role.TEACHER:
        lessons = lessons.filter(teacher=user, group__teachers=user)
    elif user.role == User.Role.STUDENT:
        profile = get_object_or_404(StudentProfile, user=user)
        lessons = lessons.filter(group=profile.group)
    elif user.role == User.Role.PARENT:
        lessons = lessons.filter(group__students__parent=user).distinct()
    elif not is_admin(user):
        raise PermissionDenied
    return render(request, "school/schedule.html", {"lessons": lessons.order_by("starts_at")})

@login_required
def ranking(request):
    if not (is_admin(request.user) or request.user.role in [User.Role.TEACHER, User.Role.STUDENT, User.Role.PARENT]):
        raise PermissionDenied
    profiles = StudentProfile.objects.select_related("user", "group").annotate(
        average_score=Avg("grades__score"), total_score=Sum("grades__score"), graded_lessons=Count("grades", distinct=True)
    )
    if request.user.role == User.Role.TEACHER:
        profiles = profiles.filter(group__teachers=request.user)
    elif request.user.role == User.Role.STUDENT:
        profiles = profiles.filter(user=request.user)
    elif request.user.role == User.Role.PARENT:
        profiles = profiles.filter(parent=request.user)
    profiles = profiles.order_by("-average_score", "-total_score", "user__last_name")
    return render(request, "school/ranking.html", {"profiles": profiles})

@login_required
def student_detail(request, student_id):
    profile = get_object_or_404(StudentProfile.objects.select_related("user", "group", "parent"), pk=student_id)
    user = request.user
    allowed = is_admin(user) or (user.role == User.Role.TEACHER and profile.group.teachers.filter(id=user.id).exists()) \
        or (user.role == User.Role.STUDENT and profile.user_id == user.id) \
        or (user.role == User.Role.PARENT and profile.parent_id == user.id)
    if not allowed:
        raise PermissionDenied
    return render(request, "school/student_detail.html", {
        "profile": profile,
        "grades": profile.grades.select_related("lesson").prefetch_related("reasons").order_by("-lesson__starts_at"),
        "attendance_records": profile.attendance.select_related("lesson").order_by("-lesson__starts_at"),
    })
