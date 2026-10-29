from django.contrib import admin
from django.urls import path
from django.contrib.auth import views as auth_views
from school import views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("login/", auth_views.LoginView.as_view(template_name="school/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", views.dashboard, name="dashboard"),
    path("baholash/", views.grade_lesson, name="grade_lesson"),
    path("jadval/", views.schedule, name="schedule"),
    path("reyting/", views.ranking, name="ranking"),
    path("oquvchi/<int:student_id>/", views.student_detail, name="student_detail"),
]
