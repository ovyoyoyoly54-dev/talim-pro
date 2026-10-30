from django.contrib import admin
from django.urls import path
from django.contrib.auth import views as auth_views
from django.views.decorators.debug import sensitive_post_parameters
from django.utils.decorators import method_decorator
from school import views


@method_decorator(sensitive_post_parameters(), name="post")
class RateLimitedLoginView(auth_views.LoginView):
    """Throttle repeated password guesses by normalized username and source IP."""

    def post(self, request, *args, **kwargs):
        from django.core.cache import cache
        from django.conf import settings
        import hashlib
        import hmac

        username = request.POST.get("username", "").strip().casefold()[:150]
        ip = request.META.get("REMOTE_ADDR", "")
        secret = settings.SECRET_KEY.encode()
        identity = hmac.new(secret, f"{username}|{ip}".encode(), hashlib.sha256).hexdigest()
        ip_identity = hmac.new(secret, ip.encode(), hashlib.sha256).hexdigest()
        keys = (f"login-rate:user:{identity}", f"login-rate:ip:{ip_identity}")
        attempts = max(cache.get(key, 0) for key in keys)
        if attempts >= settings.AUTH_RATE_LIMIT_ATTEMPTS:
            from django.contrib import messages
            messages.error(request, "Juda ko‘p urinish bo‘ldi. Birozdan so‘ng qayta urinib ko‘ring.")
            return self.get(request, *args, **kwargs)
        response = super().post(request, *args, **kwargs)
        if response.status_code == 200:
            for key in keys:
                cache.set(key, attempts + 1, settings.AUTH_RATE_LIMIT_WINDOW)
        elif response.status_code in (301, 302):
            cache.delete(keys[0])
        return response

urlpatterns = [
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
    path("", views.public_home, name="home"),
    path("baholash/", views.grade_lesson, name="grade_lesson"),
    path("jadval/", views.schedule, name="schedule"),
    path("reyting/", views.ranking, name="ranking"),
    path("oquvchi/<int:student_id>/", views.student_detail, name="student_detail"),
]
