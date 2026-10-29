from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, StudyGroup, StudentProfile, Lesson, GradeReason, GradeRecord, Attendance, SMSLog

@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("Ta'lim PRO", {"fields": ("role", "phone")}),)
    add_fieldsets = UserAdmin.add_fieldsets + (("Ta'lim PRO", {"fields": ("role", "phone")}),)
    list_display = ("username", "first_name", "last_name", "role", "phone", "is_active")
    list_filter = ("role", "is_active")

@admin.register(StudyGroup)
class StudyGroupAdmin(admin.ModelAdmin):
    list_display = ("name", "subject")
    filter_horizontal = ("teachers",)

@admin.register(StudentProfile)
class StudentProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "group", "parent")
    list_filter = ("group",)

admin.site.register(Lesson)
admin.site.register(GradeReason)
admin.site.register(GradeRecord)
admin.site.register(Attendance)
admin.site.register(SMSLog)
