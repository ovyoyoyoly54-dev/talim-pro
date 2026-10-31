from django.test import TestCase, Client
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.urls import reverse
from django.utils import timezone
from django.test import override_settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.contrib import admin
from django.test import RequestFactory
from datetime import timedelta
from unittest.mock import patch
import requests
from .models import User, StudyGroup, StudentProfile, Lesson, GradeReason, GradeRecord, Attendance, PhoneOTP, PlatformSettings
from .forms import GradeRecordForm, LessonCreateForm
from .admin import GradeRecordAdmin, GradeRecordAdminForm
from .sms import send_parent_sms


class PhoneAccountSecurityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            "phone_student", password="OldSecurePass!2026", role=User.Role.STUDENT,
            phone="+998 90 123 45 67",
        )

    @patch("school.phone_auth._send_code", return_value=True)
    def test_password_reset_requires_phone_otp_and_changes_password(self, send_code):
        response = self.client.post(reverse("password_reset"), {
            "action": "send_code", "username": self.user.username, "phone": "90 123 45 67",
        })
        self.assertRedirects(response, reverse("password_reset"))
        sent_code = send_code.call_args.args[1]
        self.assertEqual(len(sent_code), 6)
        challenge = PhoneOTP.objects.get(user=self.user, purpose=PhoneOTP.Purpose.RESET_PASSWORD)
        self.assertNotIn(sent_code, challenge.code_hash)
        wrong_code = ("0" if sent_code[0] != "0" else "1") + sent_code[1:]
        self.client.post(reverse("password_reset"), {
            "action": "reset_password", "code": wrong_code,
            "new_password": "NewSecurePass!2026", "confirm_password": "NewSecurePass!2026",
        })
        challenge.refresh_from_db()
        self.assertEqual(challenge.attempts, 1)
        response = self.client.post(reverse("password_reset"), {
            "action": "reset_password", "code": sent_code,
            "new_password": "NewSecurePass!2026", "confirm_password": "NewSecurePass!2026",
        })
        self.assertRedirects(response, reverse("login"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("NewSecurePass!2026"))
        challenge.refresh_from_db()
        self.assertIsNotNone(challenge.consumed_at)

    @patch("school.phone_auth._send_code", return_value=True)
    def test_password_reset_does_not_send_code_to_mismatched_phone(self, send_code):
        self.client.post(reverse("password_reset"), {
            "action": "send_code", "username": self.user.username, "phone": "+998 91 000 00 00",
        })
        send_code.assert_not_called()
        self.assertFalse(PhoneOTP.objects.exists())
        response = self.client.get(reverse("password_reset"))
        self.assertFalse(response.context["has_challenge"])

    @patch("school.phone_auth._send_code", return_value=True)
    def test_account_close_uses_otp_and_preserves_school_history(self, send_code):
        group = StudyGroup.objects.create(name="CloseTest", subject="Matematika")
        profile = StudentProfile.objects.create(user=self.user, group=group)
        self.client.force_login(self.user)
        self.client.post(reverse("close_account"), {"action": "send_code"})
        code = send_code.call_args.args[1]
        response = self.client.post(reverse("close_account"), {"action": "verify_code", "code": code})
        self.assertRedirects(response, reverse("close_account"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)
        self.assertContains(self.client.get(reverse("close_account")), 'name="username"')
        response = self.client.post(reverse("close_account"), {
            "action": "confirm_close", "username": self.user.username,
            "password": "OldSecurePass!2026",
        })
        self.assertRedirects(response, reverse("home"))
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)
        self.assertTrue(StudentProfile.objects.filter(pk=profile.pk).exists())

    @patch("school.phone_auth._send_code", return_value=True)
    def test_account_remains_active_when_password_confirmation_is_wrong(self, send_code):
        self.client.force_login(self.user)
        self.client.post(reverse("close_account"), {"action": "send_code"})
        code = send_code.call_args.args[1]
        self.client.post(reverse("close_account"), {"action": "verify_code", "code": code})
        response = self.client.post(reverse("close_account"), {
            "action": "confirm_close", "username": self.user.username,
            "password": "WrongPassword!2026",
        })
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)
        self.assertTrue(response.context["password_step"])

    def test_admin_cannot_close_account_from_self_service(self):
        admin_user = User.objects.create_user("phone_admin", password="StrongPassword123!", role=User.Role.ADMIN)
        self.client.force_login(admin_user)
        self.assertEqual(self.client.get(reverse("close_account")).status_code, 403)


class AdminBootstrapCommandTests(TestCase):
    @override_settings(DEBUG=False)
    @patch.dict("os.environ", {
        "DJANGO_ADMIN_USERNAME": "render_admin_test",
        "DJANGO_ADMIN_PASSWORD": "A-Long-Unique-Admin-Pass!2026",
        "DJANGO_ADMIN_EMAIL": "admin@example.invalid",
    })
    def test_command_creates_admin_once_without_rotating_existing_password(self):
        call_command("ensure_admin", stdout=None)
        admin_user = User.objects.get(username="render_admin_test")
        self.assertTrue(admin_user.is_superuser)
        self.assertTrue(admin_user.is_staff)
        self.assertEqual(admin_user.role, User.Role.ADMIN)
        self.assertTrue(admin_user.check_password("A-Long-Unique-Admin-Pass!2026"))

        with patch.dict("os.environ", {"DJANGO_ADMIN_PASSWORD": "Another-Long-Admin-Pass!2026"}):
            call_command("ensure_admin", stdout=None)
        admin_user.refresh_from_db()
        self.assertTrue(admin_user.check_password("A-Long-Unique-Admin-Pass!2026"))
        self.assertFalse(admin_user.check_password("Another-Long-Admin-Pass!2026"))


class AdminNavigationTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            "navigation_admin", "navigation@example.invalid", "StrongNavigationPass!2026",
            role=User.Role.ADMIN,
        )
        self.client.force_login(self.admin)

    def test_management_index_is_localized_and_hides_recent_actions(self):
        response = self.client.get(reverse("admin:index"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Markaz boshqaruvi")
        self.assertContains(response, "tp-admin-hero")
        self.assertContains(response, "school/admin.css")
        self.assertContains(response, "Foydalanuvchilar")
        self.assertContains(response, "O‘quv guruhlari")
        self.assertContains(response, f'href="{reverse("lesson_create")}"')
        self.assertNotContains(response, "So‘nggi harakatlar")
        self.assertNotContains(response, "Groups")

    def test_management_lists_load_the_shared_admin_stylesheet(self):
        response = self.client.get(reverse("admin:school_studygroup_changelist"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "school/admin.css")

    def test_dashboard_group_management_link_targets_groups(self):
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, f'href="{reverse("admin:school_studygroup_changelist")}"')
        self.assertContains(response, "Guruhlarni boshqarish")

    def test_dashboard_shows_admins_lessons_and_recent_grades(self):
        teacher = User.objects.create_user("dashboard_teacher", password="StrongPassword123!", role=User.Role.TEACHER)
        parent = User.objects.create_user("dashboard_parent", password="StrongPassword123!", role=User.Role.PARENT)
        student_user = User.objects.create_user("dashboard_student", password="StrongPassword123!", role=User.Role.STUDENT)
        group = StudyGroup.objects.create(name="Dashboard A1", subject="Ingliz tili")
        group.teachers.add(teacher)
        student = StudentProfile.objects.create(user=student_user, group=group, parent=parent)
        lesson = Lesson.objects.create(group=group, teacher=teacher, title="Dashboard darsi", starts_at=timezone.now() + timedelta(days=1))
        GradeRecord.objects.create(lesson=lesson, student=student, teacher=teacher, score=9)

        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, "Yaqin darslar")
        self.assertContains(response, "Dashboard darsi")
        self.assertContains(response, "So‘nggi baholar")
        self.assertContains(response, "9/10")

    def test_settings_panel_separates_site_and_account_settings(self):
        response = self.client.get(reverse("settings_panel"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sayt sozlamalari")
        self.assertContains(response, "Akkaunt ma’lumotlari")
        self.assertContains(response, "Parolni almashtirish")
        self.assertContains(response, f'href="{reverse("admin:index")}"')
        self.assertNotContains(response, f'href="{reverse("admin:school_studygroup_changelist")}"')

    def test_non_admin_settings_show_common_sections_only(self):
        teacher = User.objects.create_user("settings_teacher", password="StrongPassword123!", role=User.Role.TEACHER)
        self.client.force_login(teacher)
        response = self.client.get(reverse("settings_panel"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Akkaunt ma’lumotlari")
        self.assertContains(response, "Parolni almashtirish")
        self.assertContains(response, "Tizimdan chiqish")
        self.assertNotContains(response, "Sayt sozlamalari")
        self.assertNotContains(response, "Boshqaruv vositalari")
        self.assertNotContains(response, reverse("admin:index"))

    def test_admin_settings_show_site_settings_without_data_management_links(self):
        response = self.client.get(reverse("settings_panel"))
        self.assertContains(response, "Sayt sozlamalari")
        self.assertNotContains(response, f'href="{reverse("admin:school_user_changelist")}"')
        self.assertNotContains(response, f'href="{reverse("admin:school_studygroup_changelist")}"')
        self.assertNotContains(response, "Guruhlarni boshqarish")
        self.assertNotContains(response, "Boshqaruv vositalari")

    def test_site_settings_update_public_home(self):
        response = self.client.post(reverse("settings_panel"), {
            "action": "site_settings", "site_name": "TA’LIM PRO Markaz",
            "home_heading": "Yangi sarlavha", "home_description": "Yangilangan tavsif",
            "contact_phone": "+998901112233", "contact_email": "hello@example.invalid",
        })
        self.assertRedirects(response, reverse("settings_panel"))
        settings_obj = PlatformSettings.objects.get(pk=1)
        self.assertEqual(settings_obj.site_name, "TA’LIM PRO Markaz")
        self.client.logout()
        public = self.client.get(reverse("home"))
        self.assertContains(public, "Yangi sarlavha")
        self.assertContains(public, "Yangilangan tavsif")
        self.assertContains(public, "TA’LIM PRO Markaz")

    def test_admin_can_change_account_and_password_without_logout(self):
        response = self.client.post(reverse("settings_panel"), {
            "action": "account_settings", "username": self.admin.username,
            "first_name": "Markaz", "last_name": "Admin", "email": "new@example.invalid", "phone": "+998901234567",
        })
        self.assertRedirects(response, reverse("settings_panel"))
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.first_name, "Markaz")

        response = self.client.post(reverse("settings_panel"), {
            "action": "password_change", "old_password": "StrongNavigationPass!2026",
            "new_password1": "AnotherStrongNavigationPass!2027",
            "new_password2": "AnotherStrongNavigationPass!2027",
        })
        self.assertRedirects(response, reverse("settings_panel"))
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.check_password("AnotherStrongNavigationPass!2027"))
        self.assertEqual(self.client.get(reverse("settings_panel")).status_code, 200)

class SettingsRoleAccessTests(TestCase):
    def setUp(self):
        self.group = StudyGroup.objects.create(name="Settings A1", subject="Ingliz tili")
        self.teacher = User.objects.create_user(
            "settings_teacher_role", password="StrongPassword123!", role=User.Role.TEACHER,
            first_name="Teacher", phone="+998901111111",
        )
        self.student = User.objects.create_user(
            "settings_student_role", password="StrongPassword123!", role=User.Role.STUDENT,
            first_name="Student", phone="+998902222222",
        )
        self.parent = User.objects.create_user(
            "settings_parent_role", password="StrongPassword123!", role=User.Role.PARENT,
            first_name="Parent", phone="+998903333333",
        )
        self.admin = User.objects.create_superuser(
            "settings_admin_role", "settings-admin@example.invalid", "StrongPassword123!",
            role=User.Role.ADMIN, phone="+998904444444",
        )
        StudentProfile.objects.create(user=self.student, group=self.group, parent=self.parent)

    def test_all_roles_see_the_same_common_settings_sections(self):
        for user in (self.teacher, self.student, self.parent, self.admin):
            self.client.force_login(user)
            response = self.client.get(reverse("settings_panel"))
            self.assertEqual(response.status_code, 200, user.role)
            self.assertContains(response, "Akkaunt ma’lumotlari")
            self.assertContains(response, "Parolni almashtirish")
            self.assertContains(response, "Xavfsizlik va chiqish")
            self.assertContains(response, "Tizimdan chiqish")
            self.assertContains(response, "csrfmiddlewaretoken")
            self.assertContains(response, f'href="{reverse("settings_panel")}"')
            self.client.logout()

    def test_only_admin_sees_site_settings(self):
        for user in (self.teacher, self.student, self.parent):
            self.client.force_login(user)
            response = self.client.get(reverse("settings_panel"))
            self.assertNotContains(response, "Sayt sozlamalari")
            self.assertNotContains(response, "Boshqaruv vositalari")
            self.assertNotContains(response, "Guruhlarni boshqarish")
            self.assertNotContains(response, reverse("admin:index"))
            self.client.logout()

        self.client.force_login(self.admin)
        response = self.client.get(reverse("settings_panel"))
        self.assertContains(response, "Sayt sozlamalari")
        self.assertContains(response, f'href="{reverse("admin:index")}"')
        self.assertNotContains(response, "Boshqaruv vositalari")
        self.assertNotContains(response, f'href="{reverse("admin:school_user_changelist")}"')
        self.assertNotContains(response, f'href="{reverse("admin:school_studygroup_changelist")}"')
        self.assertNotContains(response, "Guruhlarni boshqarish")

    def test_non_admin_cannot_post_site_settings(self):
        original_name = PlatformSettings.get_solo().site_name
        self.client.force_login(self.teacher)
        response = self.client.post(reverse("settings_panel"), {
            "action": "site_settings", "site_name": "Ruxsatsiz o‘zgarish",
            "home_heading": "Ruxsatsiz", "home_description": "Ruxsatsiz",
            "contact_phone": "", "contact_email": "",
        })
        self.assertEqual(response.status_code, 403)
        self.assertEqual(PlatformSettings.get_solo().site_name, original_name)

    def test_settings_posts_require_csrf_token(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        account_response = client.post(reverse("settings_panel"), {
            "action": "account_settings", "username": self.admin.username,
            "first_name": "CSRF", "last_name": "Admin", "email": "csrf@example.invalid", "phone": "",
        })
        self.assertEqual(account_response.status_code, 403)
        site_response = client.post(reverse("settings_panel"), {
            "action": "site_settings", "site_name": "CSRF o‘zgarishi",
            "home_heading": "CSRF", "home_description": "CSRF",
            "contact_phone": "", "contact_email": "",
        })
        self.assertEqual(site_response.status_code, 403)
        self.admin.refresh_from_db()
        self.assertNotEqual(self.admin.first_name, "CSRF")
        self.assertNotEqual(PlatformSettings.get_solo().site_name, "CSRF o‘zgarishi")

    def test_invalid_profile_and_site_data_are_rejected_server_side(self):
        self.client.force_login(self.student)
        response = self.client.post(reverse("settings_panel"), {
            "action": "account_settings", "username": self.student.username,
            "first_name": "Saqlanmasligi kerak", "last_name": "Foydalanuvchi",
            "email": "not-an-email", "phone": self.student.phone,
        })
        self.assertEqual(response.status_code, 200)
        self.student.refresh_from_db()
        self.assertNotEqual(self.student.first_name, "Saqlanmasligi kerak")

        original_name = PlatformSettings.get_solo().site_name
        self.client.force_login(self.admin)
        response = self.client.post(reverse("settings_panel"), {
            "action": "site_settings", "site_name": "",
            "home_heading": "Sarlavha", "home_description": "Tavsif",
            "contact_phone": "", "contact_email": "",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(PlatformSettings.get_solo().site_name, original_name)

    def test_each_role_can_save_own_profile_without_changing_role(self):
        for user in (self.teacher, self.student, self.parent, self.admin):
            self.client.force_login(user)
            original_role = user.role
            new_first_name = f"{user.username} ism"
            response = self.client.post(reverse("settings_panel"), {
                "action": "account_settings", "username": user.username,
                "first_name": new_first_name, "last_name": "Foydalanuvchi",
                "email": f"{user.username}@example.invalid", "phone": user.phone,
                "role": User.Role.ADMIN,
            })
            self.assertRedirects(response, reverse("settings_panel"))
            user.refresh_from_db()
            self.assertEqual(user.first_name, new_first_name)
            self.assertEqual(user.role, original_role)
            self.client.logout()

    def test_password_change_requires_current_password_and_preserves_session(self):
        self.client.force_login(self.student)
        response = self.client.post(reverse("settings_panel"), {
            "action": "password_change", "old_password": "WrongPassword!2026",
            "new_password1": "AnotherStrongPass!2027", "new_password2": "AnotherStrongPass!2027",
        })
        self.assertEqual(response.status_code, 200)
        self.student.refresh_from_db()
        self.assertTrue(self.student.check_password("StrongPassword123!"))

        response = self.client.post(reverse("settings_panel"), {
            "action": "password_change", "old_password": "StrongPassword123!",
            "new_password1": "AnotherStrongPass!2027", "new_password2": "AnotherStrongPass!2027",
        })
        self.assertRedirects(response, reverse("settings_panel"))
        self.student.refresh_from_db()
        self.assertTrue(self.student.check_password("AnotherStrongPass!2027"))
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)

    def test_public_pages_do_not_expose_user_phone_or_account_data(self):
        phone = self.student.phone
        response = self.client.get(reverse("home"))
        self.assertNotContains(response, phone)
        self.assertNotContains(response, self.student.username)
        response = self.client.get(reverse("login"))
        self.assertNotContains(response, phone)
        self.assertNotContains(response, self.student.username)

    def test_settings_requires_authentication(self):
        response = self.client.get(reverse("settings_panel"))
        self.assertRedirects(response, f"{reverse('login')}?next={reverse('settings_panel')}")


class LessonCreateTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            "lesson_admin", "lesson@example.invalid", "StrongLessonPass!2026",
            role=User.Role.ADMIN,
        )
        self.teacher = User.objects.create_user(
            "lesson_teacher", password="StrongPassword123!", role=User.Role.TEACHER,
            first_name="Dars", last_name="O‘qituvchi",
        )
        self.other_teacher = User.objects.create_user(
            "other_lesson_teacher", password="StrongPassword123!", role=User.Role.TEACHER,
            first_name="Boshqa", last_name="O‘qituvchi",
        )
        self.student = User.objects.create_user(
            "lesson_student", password="StrongPassword123!", role=User.Role.STUDENT,
        )
        self.parent = User.objects.create_user(
            "lesson_parent", password="StrongPassword123!", role=User.Role.PARENT,
        )
        self.group = StudyGroup.objects.create(name="Lesson A1", subject="Ingliz tili")
        self.group.teachers.add(self.teacher)
        self.other_group = StudyGroup.objects.create(name="Lesson B1", subject="Matematika")
        self.other_group.teachers.add(self.other_teacher)
        self.starts_at = (timezone.localtime() + timedelta(days=1)).replace(second=0, microsecond=0)
        self.starts_value = self.starts_at.strftime("%Y-%m-%dT%H:%M")

    def payload(self, **overrides):
        data = {
            "title": "Present Simple",
            "group": self.group.pk,
            "teacher": self.teacher.pk,
            "starts_at": self.starts_value,
            "room": "201-xona",
        }
        data.update(overrides)
        return data

    def test_admin_can_open_clear_lesson_create_form(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("lesson_create"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Dars mavzusi")
        self.assertContains(response, "O‘quv guruhi")
        self.assertContains(response, "O‘qituvchi")
        self.assertContains(response, "Sana va vaqt")
        self.assertContains(response, "Xona")
        self.assertContains(response, 'type="datetime-local"')

    def test_admin_can_create_lesson_and_redirect_to_schedule(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("lesson_create"), self.payload())
        self.assertRedirects(response, reverse("schedule"))
        lesson = Lesson.objects.get(title="Present Simple")
        self.assertEqual(lesson.group, self.group)
        self.assertEqual(lesson.teacher, self.teacher)
        self.assertEqual(lesson.starts_at, self.starts_at)
        self.assertEqual(lesson.room, "201-xona")

    def test_only_admin_can_open_and_submit_lesson_create(self):
        for user in (self.teacher, self.student, self.parent):
            self.client.force_login(user)
            self.assertEqual(self.client.get(reverse("lesson_create")).status_code, 403)
            self.assertEqual(self.client.post(reverse("lesson_create"), self.payload()).status_code, 403)
            self.client.logout()
        self.assertFalse(Lesson.objects.exists())

    def test_lesson_create_requires_login(self):
        response = self.client.get(reverse("lesson_create"))
        self.assertRedirects(response, f"{reverse('login')}?next={reverse('lesson_create')}")

    def test_lesson_create_requires_csrf_token(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        response = client.post(reverse("lesson_create"), self.payload())
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Lesson.objects.exists())

    def test_teacher_queryset_contains_only_active_teachers(self):
        inactive = User.objects.create_user(
            "inactive_lesson_teacher", password="StrongPassword123!",
            role=User.Role.TEACHER, is_active=False,
        )
        form = LessonCreateForm()
        self.assertIn(self.teacher, form.fields["teacher"].queryset)
        self.assertIn(self.other_teacher, form.fields["teacher"].queryset)
        self.assertNotIn(self.admin, form.fields["teacher"].queryset)
        self.assertNotIn(self.student, form.fields["teacher"].queryset)
        self.assertNotIn(inactive, form.fields["teacher"].queryset)

    def test_teacher_must_be_assigned_to_selected_group(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("lesson_create"), self.payload(teacher=self.other_teacher.pk))
        self.assertEqual(response.status_code, 200)
        self.assertIn("teacher", response.context["form"].errors)
        self.assertContains(response, "guruhga biriktirilmagan")
        self.assertFalse(Lesson.objects.exists())

    def test_past_lesson_time_is_rejected(self):
        past = (timezone.localtime() - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
        self.client.force_login(self.admin)
        response = self.client.post(reverse("lesson_create"), self.payload(starts_at=past))
        self.assertEqual(response.status_code, 200)
        self.assertIn("starts_at", response.context["form"].errors)
        self.assertContains(response, "kelajakda bo‘lishi kerak")
        self.assertFalse(Lesson.objects.exists())

    def test_duplicate_group_time_is_rejected(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("lesson_create"), self.payload())
        response = self.client.post(reverse("lesson_create"), self.payload(title="Takroriy dars"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("group", response.context["form"].errors)
        self.assertContains(response, "aynan shu vaqtda dars mavjud")
        self.assertEqual(Lesson.objects.count(), 1)

    def test_teacher_double_booking_is_rejected(self):
        self.other_group.teachers.add(self.teacher)
        Lesson.objects.create(
            group=self.other_group, teacher=self.teacher, title="Boshqa guruh darsi",
            starts_at=self.starts_at, room="101-xona",
        )
        self.client.force_login(self.admin)
        response = self.client.post(reverse("lesson_create"), self.payload(room="202-xona"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("teacher", response.context["form"].errors)
        self.assertContains(response, "boshqa darsi bor")
        self.assertEqual(Lesson.objects.count(), 1)

    def test_room_double_booking_is_rejected(self):
        Lesson.objects.create(
            group=self.other_group, teacher=self.other_teacher, title="Boshqa dars",
            starts_at=self.starts_at, room="201-xona",
        )
        self.client.force_login(self.admin)
        response = self.client.post(reverse("lesson_create"), self.payload())
        self.assertEqual(response.status_code, 200)
        self.assertIn("room", response.context["form"].errors)
        self.assertContains(response, "xona aynan shu vaqtda band")
        self.assertEqual(Lesson.objects.count(), 1)

    def test_model_rejects_teacher_not_assigned_to_group(self):
        with self.assertRaises(ValidationError):
            Lesson.objects.create(
                group=self.group, teacher=self.other_teacher, title="Noto‘g‘ri bog‘lanish",
                starts_at=self.starts_at, room="",
            )

    def test_lesson_create_links_are_visible_only_to_admin(self):
        self.client.force_login(self.admin)
        for url_name in ("dashboard", "schedule"):
            response = self.client.get(reverse(url_name))
            self.assertContains(response, f'href="{reverse("lesson_create")}"')
        self.client.force_login(self.teacher)
        for url_name in ("dashboard", "schedule"):
            response = self.client.get(reverse(url_name))
            self.assertNotContains(response, f'href="{reverse("lesson_create")}"')


class LessonRescheduleTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(
            "reschedule_teacher", password="StrongPassword123!", role=User.Role.TEACHER,
        )
        self.other_teacher = User.objects.create_user(
            "reschedule_other", password="StrongPassword123!", role=User.Role.TEACHER,
        )
        self.group = StudyGroup.objects.create(name="Reschedule A1", subject="Ingliz tili")
        self.group.teachers.add(self.teacher)
        self.other_group = StudyGroup.objects.create(name="Reschedule B1", subject="Matematika")
        self.other_group.teachers.add(self.other_teacher)
        self.lesson = Lesson.objects.create(
            group=self.group, teacher=self.teacher, title="Mening darsim",
            starts_at=timezone.now() + timedelta(days=2), room="101-xona",
        )
        self.other_lesson = Lesson.objects.create(
            group=self.other_group, teacher=self.other_teacher, title="Boshqa dars",
            starts_at=timezone.now() + timedelta(days=3), room="102-xona",
        )

    def test_teacher_can_reschedule_only_their_own_lesson(self):
        self.client.force_login(self.teacher)
        new_time = timezone.localtime(timezone.now() + timedelta(days=4)).replace(second=0, microsecond=0)

        response = self.client.post(
            reverse("lesson_reschedule", kwargs={"lesson_id": self.lesson.pk}),
            {"starts_at": new_time.strftime("%Y-%m-%dT%H:%M")},
        )

        self.assertRedirects(response, reverse("schedule"))
        self.lesson.refresh_from_db()
        self.assertEqual(self.lesson.starts_at, new_time)

    def test_teacher_cannot_reschedule_another_teachers_lesson(self):
        self.client.force_login(self.teacher)

        response = self.client.get(reverse("lesson_reschedule", kwargs={"lesson_id": self.other_lesson.pk}))

        self.assertEqual(response.status_code, 403)


class PlatformRulesTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("admin1", password="StrongPassword123!", role=User.Role.ADMIN)
        self.teacher = User.objects.create_user("teacher1", password="StrongPassword123!", role=User.Role.TEACHER)
        self.student_user = User.objects.create_user("student1", password="StrongPassword123!", role=User.Role.STUDENT, first_name="Ali")
        self.group = StudyGroup.objects.create(name="A1", subject="Ingliz tili")
        self.group.teachers.add(self.teacher)
        self.profile = StudentProfile.objects.create(user=self.student_user, group=self.group)
        self.lesson = Lesson.objects.create(group=self.group, title="Present Simple", starts_at=timezone.now()+timedelta(days=1), teacher=self.teacher)
        self.reason = GradeReason.objects.create(title="Uy vazifasini bajarmadi")

    def test_group_limit_is_five(self):
        for n in range(2, 6):
            StudyGroup.objects.create(name=f"G{n}", subject="Matematika")
        with self.assertRaises(ValidationError):
            StudyGroup.objects.create(name="G6", subject="IT")

    def test_score_range_database_constraint(self):
        record = GradeRecord(lesson=self.lesson, student=self.profile, score=11, teacher=self.teacher)
        with self.assertRaises(ValidationError):
            record.full_clean()

    def test_below_eight_requires_reason_in_form(self):
        form = GradeRecordForm(data={
            "lesson": self.lesson.pk, "student": self.profile.pk, "score": "6",
            "note": "", "attendance": Attendance.Status.PRESENT,
        }, teacher=self.teacher)
        self.assertFalse(form.is_valid())
        self.assertIn("reasons", form.errors)

    def test_model_rejects_new_low_grade_without_reason(self):
        record = GradeRecord(lesson=self.lesson, student=self.profile, score=6, teacher=self.teacher)
        with self.assertRaises(ValidationError):
            record.full_clean()
        with self.assertRaises(ValidationError):
            record.save()

    def test_low_grade_reason_cannot_be_removed_from_model_relation(self):
        record = GradeRecord.objects.create(lesson=self.lesson, student=self.profile, score=8, teacher=self.teacher)
        record.reasons.add(self.reason)
        record.score = 6
        record.save()
        with self.assertRaises(ValidationError):
            self.reason.delete()
        with self.assertRaises(ValidationError):
            GradeReason.objects.filter(pk=self.reason.pk).delete()
        with self.assertRaises(ValidationError):
            record.reasons.clear()

    def test_admin_save_keeps_low_grade_reason_attached(self):
        form = GradeRecordAdminForm(data={
            "lesson": self.lesson.pk, "student": self.profile.pk, "score": "5",
            "reasons": [self.reason.pk], "note": "", "teacher": self.teacher.pk,
        })
        self.assertTrue(form.is_valid(), form.errors)
        record = form.save(commit=False)
        model_admin = GradeRecordAdmin(GradeRecord, admin.site)
        request = RequestFactory().post("/admin/school/graderecord/add/")
        model_admin.save_model(request, record, form, change=False)
        model_admin.save_related(request, form, formsets=[], change=False)
        self.assertEqual(record.score, 5)
        self.assertTrue(record.reasons.filter(pk=self.reason.pk).exists())

    def test_admin_form_requires_and_saves_low_grade_reason(self):
        data = {
            "lesson": self.lesson.pk, "student": self.profile.pk, "score": "6",
            "reasons": [], "note": "", "teacher": self.teacher.pk,
        }
        form = GradeRecordAdminForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn("reasons", form.errors)

        data["reasons"] = [self.reason.pk]
        form = GradeRecordAdminForm(data=data)
        self.assertTrue(form.is_valid(), form.errors)
        record = form.save()
        self.assertEqual(record.score, 6)
        self.assertTrue(record.reasons.filter(pk=self.reason.pk).exists())

    def test_teacher_can_open_grade_page(self):
        client = Client()
        client.force_login(self.teacher)
        response = client.get(reverse("grade_lesson"))
        self.assertEqual(response.status_code, 200)

    def test_student_cannot_open_grade_page(self):
        client = Client()
        client.force_login(self.student_user)
        response = client.get(reverse("grade_lesson"))
        self.assertEqual(response.status_code, 403)

    def test_student_cannot_view_another_student_profile(self):
        other_user = User.objects.create_user("student2", password="StrongPassword123!", role=User.Role.STUDENT)
        other_profile = StudentProfile.objects.create(user=other_user, group=self.group)
        client = Client()
        client.force_login(self.student_user)
        response = client.get(reverse("student_detail", args=[other_profile.pk]))
        self.assertEqual(response.status_code, 403)

    def test_student_can_view_own_profile(self):
        client = Client()
        client.force_login(self.student_user)
        response = client.get(reverse("student_detail", args=[self.profile.pk]))
        self.assertEqual(response.status_code, 200)

    def test_parent_cannot_view_an_unlinked_student_profile(self):
        parent = User.objects.create_user("parent1", password="StrongPassword123!", role=User.Role.PARENT)
        other_user = User.objects.create_user("student2", password="StrongPassword123!", role=User.Role.STUDENT)
        other_profile = StudentProfile.objects.create(user=other_user, group=self.group)
        client = Client()
        client.force_login(parent)
        response = client.get(reverse("student_detail", args=[other_profile.pk]))
        self.assertEqual(response.status_code, 403)

    def test_parent_can_view_linked_child_profile(self):
        parent = User.objects.create_user("parent1", password="StrongPassword123!", role=User.Role.PARENT)
        self.profile.parent = parent
        self.profile.save()
        client = Client()
        client.force_login(parent)
        response = client.get(reverse("student_detail", args=[self.profile.pk]))
        self.assertEqual(response.status_code, 200)

    def test_group_isolation_hides_another_groups_student_from_teacher(self):
        other_group = StudyGroup.objects.create(name="B1", subject="Matematika")
        other_user = User.objects.create_user("student2", password="StrongPassword123!", role=User.Role.STUDENT)
        other_profile = StudentProfile.objects.create(user=other_user, group=other_group)
        client = Client()
        client.force_login(self.teacher)
        response = client.get(reverse("student_detail", args=[other_profile.pk]))
        self.assertEqual(response.status_code, 403)

    def test_teacher_ranking_is_limited_to_assigned_groups(self):
        other_group = StudyGroup.objects.create(name="B1", subject="Matematika")
        other_user = User.objects.create_user("student2", password="StrongPassword123!", role=User.Role.STUDENT)
        StudentProfile.objects.create(user=other_user, group=other_group)
        client = Client()
        client.force_login(self.teacher)
        response = client.get(reverse("ranking"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["profiles"]), [self.profile])

    def test_public_home_is_indexable_but_dashboard_is_not_public(self):
        client = Client()
        response = client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="robots" content="index,follow"')
        self.assertContains(response, 'rel="canonical"')
        self.assertContains(response, 'href="/static/school/app.css"')
        self.assertRedirects(client.get(reverse("dashboard")), f"{reverse('login')}?next={reverse('dashboard')}")

    @override_settings(PUBLIC_SITE_URL="")
    def test_sitemap_contains_only_public_home_and_robots_excludes_private_urls(self):
        client = Client()
        sitemap = client.get(reverse("sitemap_xml"))
        self.assertEqual(sitemap.status_code, 200)
        self.assertEqual(sitemap["Content-Type"], "application/xml; charset=utf-8")
        self.assertEqual(sitemap.content.count(b"<url>"), 1)
        self.assertIn(b"<loc>http://testserver/</loc>", sitemap.content)
        robots = client.get(reverse("robots_txt"))
        self.assertContains(robots, "Disallow: /oquvchi/")
        self.assertContains(robots, "Disallow: /dars-qoshish/")
        self.assertContains(robots, "Disallow: /dashboard/")
        self.assertContains(robots, "Disallow: /parolni-tiklash/")
        self.assertContains(robots, "Sitemap: http://testserver/sitemap.xml")

    @override_settings(DEBUG=False)
    def test_seed_demo_refuses_to_run_outside_debug(self):
        with self.assertRaises(CommandError):
            call_command("seed_demo", stdout=None)

    def test_sms_failure_log_does_not_store_request_exception_url_or_token(self):
        parent = User.objects.create_user("parent_sms", password="StrongPassword123!", role=User.Role.PARENT, phone="+998901234567")
        with patch.dict("os.environ", {
            "SMS_API_URL": "https://provider.example/send?key=private-marker",
            "SMS_API_TOKEN": "private-marker",
        }), patch("school.sms.requests.post", side_effect=requests.Timeout("timeout at https://provider.example/send?key=private-marker")):
            log = send_parent_sms(parent=parent, student=self.profile, body="Baholash xabari")
        self.assertEqual(log.status, "failed")
        self.assertNotIn("private-marker", log.provider_response)
class AddStudentToGroupTests(TestCase):
    """O'quvchini guruhga qo'shish funksiyasi uchun testlar."""

    def setUp(self):
        self.teacher = User.objects.create_user(
            "add_teacher", password="StrongPassword123!", role=User.Role.TEACHER,
            first_name="Teacher", last_name="One",
        )
        self.other_teacher = User.objects.create_user(
            "other_teacher", password="StrongPassword123!", role=User.Role.TEACHER,
            first_name="Other", last_name="Teacher",
        )
        self.student_user = User.objects.create_user(
            "add_student", password="StrongPassword123!", role=User.Role.STUDENT,
            first_name="Ali", last_name="Valiyev",
        )
        self.inactive_student = User.objects.create_user(
            "inactive_student", password="StrongPassword123!", role=User.Role.STUDENT,
            first_name="Inactive", last_name="Learner", is_active=False,
        )
        self.non_student = User.objects.create_user(
            "not_student", password="StrongPassword123!", role=User.Role.PARENT,
            first_name="Not", last_name="Student",
        )
        self.already_in_group = User.objects.create_user(
            "in_group", password="StrongPassword123!", role=User.Role.STUDENT,
            first_name="In", last_name="Group",
        )
        self.group = StudyGroup.objects.create(name="A1", subject="Ingliz tili")
        self.group.teachers.add(self.teacher)
        Lesson.objects.create(
            group=self.group, teacher=self.teacher, title="O‘qituvchi darsi",
            starts_at=timezone.now() + timedelta(days=1), room="",
        )
        # already_in_group is already in the group
        StudentProfile.objects.create(user=self.already_in_group, group=self.group)
        # Non-student already has a profile too (should not appear)
        StudentProfile.objects.create(user=self.non_student, group=self.group)

    def test_teacher_can_access_add_student_page(self):
        self.client.force_login(self.teacher)
        response = self.client.get(reverse("add_student_to_group", kwargs={"group_id": self.group.pk}))
        self.assertEqual(response.status_code, 200)

    def test_other_teacher_cannot_access(self):
        self.client.force_login(self.other_teacher)
        response = self.client.get(reverse("add_student_to_group", kwargs={"group_id": self.group.pk}))
        self.assertEqual(response.status_code, 403)

    def test_assigned_teacher_without_a_lesson_cannot_add_students(self):
        group_without_lesson = StudyGroup.objects.create(name="A2", subject="Matematika")
        group_without_lesson.teachers.add(self.teacher)
        self.client.force_login(self.teacher)
        response = self.client.get(reverse("add_student_to_group", kwargs={"group_id": group_without_lesson.pk}))
        self.assertEqual(response.status_code, 403)

    def test_student_cannot_access(self):
        self.client.force_login(self.student_user)
        response = self.client.get(reverse("add_student_to_group", kwargs={"group_id": self.group.pk}))
        self.assertEqual(response.status_code, 403)

    def test_unassigned_student_appears_in_list(self):
        self.client.force_login(self.teacher)
        response = self.client.get(reverse("add_student_to_group", kwargs={"group_id": self.group.pk}))
        self.assertContains(response, "Ali Valiyev")

    def test_already_assigned_student_does_not_appear(self):
        self.client.force_login(self.teacher)
        response = self.client.get(reverse("add_student_to_group", kwargs={"group_id": self.group.pk}))
        self.assertNotContains(response, "In Group")

    def test_non_student_does_not_appear(self):
        self.client.force_login(self.teacher)
        response = self.client.get(reverse("add_student_to_group", kwargs={"group_id": self.group.pk}))
        self.assertNotContains(response, "Not Student")

    def test_inactive_student_does_not_appear(self):
        self.client.force_login(self.teacher)
        response = self.client.get(reverse("add_student_to_group", kwargs={"group_id": self.group.pk}))
        self.assertNotContains(response, "Inactive Learner")

    def test_student_username_is_not_shown_in_candidate_list(self):
        self.client.force_login(self.teacher)
        response = self.client.get(reverse("add_student_to_group", kwargs={"group_id": self.group.pk}))
        self.assertContains(response, "Ali Valiyev")
        self.assertNotContains(response, self.student_user.username)

    def test_search_filters_by_first_name(self):
        self.client.force_login(self.teacher)
        response = self.client.get(
            reverse("add_student_to_group", kwargs={"group_id": self.group.pk}) + "?search=Ali"
        )
        self.assertContains(response, "Ali Valiyev")

    def test_search_filters_by_last_name(self):
        self.client.force_login(self.teacher)
        response = self.client.get(
            reverse("add_student_to_group", kwargs={"group_id": self.group.pk}) + "?search=Valiyev"
        )
        self.assertContains(response, "Ali Valiyev")

    def test_successful_add_creates_student_profile(self):
        self.client.force_login(self.teacher)
        self.assertFalse(StudentProfile.objects.filter(user=self.student_user).exists())
        response = self.client.post(
            reverse("add_student_to_group", kwargs={"group_id": self.group.pk}),
            {"student": self.student_user.pk},
        )
        self.assertRedirects(response, reverse("add_student_to_group", kwargs={"group_id": self.group.pk}))
        self.student_user.refresh_from_db()
        self.assertTrue(hasattr(self.student_user, "student_profile"))
        profile = StudentProfile.objects.get(user=self.student_user)
        self.assertEqual(profile.group, self.group)

    def test_cannot_add_student_already_in_group(self):
        # already_in_group has a profile in this group, so not in queryset
        self.client.force_login(self.teacher)
        response = self.client.post(
            reverse("add_student_to_group", kwargs={"group_id": self.group.pk}),
            {"student": self.already_in_group.pk},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "mavjud tanlovlardan biri emas")

    def test_cannot_add_non_student_account(self):
        # non_student is PARENT role (not STUDENT), not in queryset
        self.client.force_login(self.teacher)
        response = self.client.post(
            reverse("add_student_to_group", kwargs={"group_id": self.group.pk}),
            {"student": self.non_student.pk},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "mavjud tanlovlardan biri emas")

    def test_cannot_add_inactive_student_account(self):
        self.client.force_login(self.teacher)
        response = self.client.post(
            reverse("add_student_to_group", kwargs={"group_id": self.group.pk}),
            {"student": self.inactive_student.pk},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(StudentProfile.objects.filter(user=self.inactive_student).exists())

    @patch("school.views.StudentProfile.objects.create", side_effect=IntegrityError("duplicate profile"))
    def test_concurrent_duplicate_add_returns_a_safe_message(self, create_profile):
        self.client.force_login(self.teacher)
        response = self.client.post(
            reverse("add_student_to_group", kwargs={"group_id": self.group.pk}),
            {"student": self.student_user.pk},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "boshqa so‘rovda")

    def test_empty_list_when_no_unassigned_students(self):
        # Assign the only unassigned student
        StudentProfile.objects.create(user=self.student_user, group=self.group)
        self.client.force_login(self.teacher)
        response = self.client.get(reverse("add_student_to_group", kwargs={"group_id": self.group.pk}))
        self.assertContains(response, "yo'q")

class MissingStudentProfileTests(TestCase):
    """Guruhga biriktirilmagan o'quvchi uchun sahifalar 404 bermasligi kerak."""

    def setUp(self):
        self.group = StudyGroup.objects.create(name="Profil A1", subject="Ingliz tili")
        self.student_without_group = User.objects.create_user(
            "no_group_student", password="StrongPassword123!", role=User.Role.STUDENT,
            first_name="Guruhsiz", last_name="O‘quvchi",
        )
        self.student_with_group = User.objects.create_user(
            "with_group_student", password="StrongPassword123!", role=User.Role.STUDENT,
            first_name="Guruhli", last_name="O‘quvchi",
        )
        StudentProfile.objects.create(user=self.student_with_group, group=self.group)

    def test_dashboard_without_profile_renders_friendly_message(self):
        self.client.force_login(self.student_without_group)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["missing_profile"])
        self.assertContains(response, "o‘quv guruhi biriktirilmagan")

    def test_schedule_without_profile_renders_empty_timetable(self):
        self.client.force_login(self.student_without_group)
        response = self.client.get(reverse("schedule"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["missing_profile"])
        self.assertEqual(len(response.context["lessons"]), 0)
        self.assertContains(response, "o‘quv guruhi biriktirilmagan")

    def test_student_with_profile_still_sees_group_data(self):
        self.client.force_login(self.student_with_group)
        dashboard = self.client.get(reverse("dashboard"))
        self.assertEqual(dashboard.status_code, 200)
        self.assertFalse(dashboard.context.get("missing_profile", False))
        self.assertContains(dashboard, "Profil A1")
        schedule = self.client.get(reverse("schedule"))
        self.assertEqual(schedule.status_code, 200)
        self.assertFalse(schedule.context["missing_profile"])


class LoginRedirectTests(TestCase):
    def test_authenticated_user_is_redirected_away_from_login_page(self):
        user = User.objects.create_user(
            "login_redirect_user", password="StrongPassword123!", role=User.Role.STUDENT,
        )
        StudentProfile.objects.create(user=user, group=StudyGroup.objects.create(name="Login A1", subject="Matematika"))
        self.client.force_login(user)
        response = self.client.get(reverse("login"))
        self.assertRedirects(response, reverse("dashboard"))

