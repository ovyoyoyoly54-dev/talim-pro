from django.contrib import admin
from django.urls import path
from django.contrib.auth import views as auth_views
from school import views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("robots.txt", views.robots_txt, name="robots_txt"),
    path("sitemap.xml", views.sitemap_xml, name="sitemap_xml"),
    path("login/", auth_views.LoginView.as_view(template_name="school/login.html"), name="login"),
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
