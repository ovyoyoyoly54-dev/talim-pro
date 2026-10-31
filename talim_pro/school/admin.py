from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import Group
from django import forms
from .models import User, StudyGroup, StudentProfile, Lesson, GradeReason, GradeRecord, Attendance, SMSLog

admin.site.site_header = "TA’LIM PRO — Boshqaruv"
admin.site.site_title = "TA’LIM PRO"
admin.site.index_title = "Markaz boshqaruv paneli"
admin.site.index_template = "admin/index.html"
admin.site.unregister(Group)

@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("Ta'lim PRO", {"fields": ("role", "phone")}),)
    add_fieldsets = UserAdmin.add_fieldsets + (("Ta'lim PRO", {"fields": ("role", "phone")}),)
    list_display = ("username", "first_name", "last_name", "role", "phone", "is_active")
    list_filter = ("role", "is_active")
    search_fields = ("username", "first_name", "last_name", "phone")
    ordering = ("last_name", "first_name", "username")

@admin.register(StudyGroup)
class StudyGroupAdmin(admin.ModelAdmin):
    list_display = ("name", "subject")
    filter_horizontal = ("teachers",)

@admin.register(StudentProfile)
class StudentProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "group", "parent")
    list_filter = ("group",)

@admin.register(GradeReason)
class GradeReasonAdmin(admin.ModelAdmin):
    list_display = ("title", "active")
    list_editable = ("active",)
    search_fields = ("title",)

    def has_delete_permission(self, request, obj=None):
        return False


class GradeRecordAdminForm(forms.ModelForm):
    class Meta:
        model = GradeRecord
        fields = "__all__"

    def clean(self):
        cleaned = super().clean()
        score = cleaned.get("score")
        reasons = cleaned.get("reasons")
        if score is not None and score < 8 and not reasons:
            self.add_error("reasons", "8 dan past baho uchun kamida bitta sabab tanlang.")
        self.instance._pending_reasons = reasons
        return cleaned


@admin.register(GradeRecord)
class GradeRecordAdmin(admin.ModelAdmin):
    form = GradeRecordAdminForm
    list_display = ("lesson", "student", "score", "teacher", "updated_at")
    list_filter = ("score", "lesson__group")
    search_fields = ("student__user__username", "student__user__first_name", "lesson__title")

    def save_model(self, request, obj, form, change):
        form._pending_low_score = obj.score if obj.score < 8 else None
        if form._pending_low_score is not None:
            obj.score = 8
        super().save_model(request, obj, form, change)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        final_score = getattr(form, "_pending_low_score", None)
        if final_score is not None:
            form.instance.score = final_score
            form.instance.save()
        form.instance.__dict__.pop("_pending_reasons", None)


@admin.register(SMSLog)
class SMSLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "status", "parent", "student")
    list_filter = ("status", "created_at")
    search_fields = ("parent__username", "student__user__username")
    readonly_fields = ("parent", "student", "body", "status", "provider_response", "created_at")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ("title", "group", "teacher", "starts_at", "room")
    list_filter = ("group", "teacher", "starts_at")
    search_fields = ("title", "group__name", "teacher__username", "teacher__first_name", "teacher__last_name", "room")
    date_hierarchy = "starts_at"
    ordering = ("starts_at",)


admin.site.register(Attendance)
