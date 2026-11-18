import hashlib
import hmac

from django.conf import settings
from django.contrib import admin, messages
from django.core.cache import cache
from django.urls import path
from django.contrib.auth import views as auth_views
from django.views.decorators.debug import sensitive_post_parameters
from django.utils.decorators import method_decorator
from django.views.i18n import set_language
from school import views, views_payments, views_homework, views_notifications, views_public, views_reports, views_security, gateways
from school.utils import get_client_ip


@method_decorator(sensitive_post_parameters(), name="post")
class RateLimitedLoginView(auth_views.LoginView):
    """Throttle repeated password guesses by normalized username and source IP."""

    # Tizimga kirgan foydalanuvchi login sahifasini emas, bosh sahifani ko'radi.
    redirect_authenticated_user = True

    def post(self, request, *args, **kwargs):
        username = request.POST.get("username", "").strip().casefold()[:150]
        ip = get_client_ip(request)
        secret = settings.SECRET_KEY.encode()
        identity = hmac.new(secret, f"{username}|{ip}".encode(), hashlib.sha256).hexdigest()
        ip_identity = hmac.new(secret, ip.encode(), hashlib.sha256).hexdigest()
        keys = (f"login-rate:user:{identity}", f"login-rate:ip:{ip_identity}")
        attempts = max(cache.get(key, 0) for key in keys)
        if attempts >= settings.AUTH_RATE_LIMIT_ATTEMPTS:
            messages.error(request, "Juda ko‘p urinish bo‘ldi. Birozdan so‘ng qayta urinib ko‘ring.")
            return self.get(request, *args, **kwargs)
        response = super().post(request, *args, **kwargs)
        if response.status_code == 200:
            for key in keys:
                cache.set(key, attempts + 1, settings.AUTH_RATE_LIMIT_WINDOW)
        elif response.status_code in (301, 302):
            # Muvaffaqiyatli kirishdan keyin username va IP hisoblagichlarini
            # birgalikda tozalaymiz: eski IP limiti boshqa akkauntni bloklamasin.
            for key in keys:
                cache.delete(key)
        return response

urlpatterns = [
    # Django admin kirish sahifasi urinishlarni cheklamaydi; shuning uchun /admin/login/
    # ham xuddi shu cheklovli kirish ko'rinishiga yo'naltiriladi. Admin 2FA baribir
    # TwoFactorMiddleware orqali majburlanadi. Kirgan, lekin staff bo'lmagan foydalanuvchi
    # uchun aylanma yo'naltirish bo'lmasligi uchun redirect_authenticated_user o'chirilgan.
    path("admin/login/", RateLimitedLoginView.as_view(
        template_name="school/login.html", redirect_authenticated_user=False), name="admin_login"),
    path("admin/", admin.site.urls),
    path("robots.txt", views.robots_txt, name="robots_txt"),
    path("sitemap.xml", views.sitemap_xml, name="sitemap_xml"),
    path("login/", RateLimitedLoginView.as_view(template_name="school/login.html"), name="login"),
    path("royxatdan-otish/", views.signup, name="signup"),
    path("parolni-tiklash/", views.password_reset, name="password_reset"),
    path("akkauntni-yopish/", views.close_account, name="close_account"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("service-worker.js", views.service_worker, name="service_worker"),
    path("manifest.webmanifest", views.web_manifest, name="web_manifest"),
    path("offline/", views.offline_page, name="offline_page"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("birinchi-kirish/", views.first_login_credentials, name="first_login_credentials"),
    path("guruhlar/", views.group_management, name="group_management"),
    path("guruh/<int:group_id>/", views.group_detail, name="group_detail"),
    path("oqituvchilar/", views.teacher_management, name="teacher_management"),
    path("oqituvchilar/<int:teacher_id>/guruhga-biriktirish/", views.teacher_assign_group, name="teacher_assign_group"),
    path("sozlamalar/", views.settings_panel, name="settings_panel"),
    path("", views.public_home, name="home"),
    path("baholash/", views.grade_lesson, name="grade_lesson"),
    path("dars-qoshish/", views.lesson_create, name="lesson_create"),
    path("dars/<int:lesson_id>/vaqtini-ozgartirish/", views.lesson_reschedule, name="lesson_reschedule"),
    path("jadval/", views.schedule, name="schedule"),
    path("reyting/", views.ranking, name="ranking"),
    path("oquvchi/<int:student_id>/", views.student_detail, name="student_detail"),
    path("guruh/<int:group_id>/oquvchi-qoshish/", views.add_student_to_group, name="add_student_to_group"),
    # Til
    path("til/", set_language, name="set_language"),
    # To'lovlar
    path("tolovlar/", views_payments.payments_entry, name="payments_overview"),
    path("tolovlar/hisob-yaratish/", views_payments.generate_invoices_view, name="generate_invoices"),
    path("tolovlar/qarzdorlar/", views_payments.debtors_list, name="debtors_list"),
    path("tolovlar/qarzdorlar/eslatma/", views_payments.remind_debtors, name="remind_debtors"),
    path("tolovlar/<int:invoice_id>/qabul/", views_payments.record_payment, name="record_payment"),
    path("tolovlar/<int:invoice_id>/bekor/", views_payments.cancel_invoice, name="cancel_invoice"),
    path("tolov/click/", gateways.click_webhook, name="click_webhook"),
    path("tolov/payme/", gateways.payme_webhook, name="payme_webhook"),
    # Uyga vazifa
    path("vazifalar/", views_homework.homework_list, name="homework_list"),
    path("vazifalar/yangi/", views_homework.homework_create, name="homework_create"),
    path("vazifalar/<int:homework_id>/", views_homework.homework_detail, name="homework_detail"),
    path("vazifalar/<int:homework_id>/fayl/", views_homework.homework_task_file, name="homework_task_file"),
    path("vazifalar/javob/<int:submission_id>/fayl/", views_homework.homework_answer_file, name="homework_answer_file"),
    # Bildirishnomalar
    path("bildirishnomalar/", views_notifications.notification_list, name="notification_list"),
    path("bildirishnomalar/oqildi/", views_notifications.notifications_mark_read, name="notifications_mark_read"),
    path("bildirishnomalar/push/obuna/", views_notifications.push_subscribe, name="push_subscribe"),
    path("bildirishnomalar/push/bekor/", views_notifications.push_unsubscribe, name="push_unsubscribe"),
    # Ochiq sahifalar
    path("kurslar/", views_public.courses_list, name="courses_list"),
    path("kurslar/<slug:slug>/", views_public.course_detail, name="course_detail"),
    path("narxlar/", views_public.pricing, name="pricing"),
    path("ariza/", views_public.apply, name="apply"),
    path("ariza/qabul-qilindi/", views_public.apply_done, name="apply_done"),
    path("arizalar/", views_public.applications_list, name="applications_list"),
    # Hisobotlar
    path("hisobot/", views_reports.reports_home, name="reports_home"),
    path("hisobot/davomat/", views_reports.attendance_report, name="attendance_report"),
    path("hisobot/reyting/", views_reports.ranking_report, name="ranking_report"),
    # 2FA
    path("2fa/sozlash/", views_security.two_factor_setup, name="two_factor_setup"),
    path("2fa/tekshirish/", views_security.two_factor_verify, name="two_factor_verify"),
]
