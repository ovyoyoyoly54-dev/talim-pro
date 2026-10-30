from django.test import TestCase, Client
from django.core.exceptions import ValidationError
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
from .forms import GradeRecordForm
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
        self.assertNotContains(response, "So‘nggi harakatlar")
        self.assertNotContains(response, "Groups")

    def test_dashboard_group_management_link_targets_groups(self):
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, f'href="{reverse("admin:school_studygroup_changelist")}"')
        self.assertContains(response, "Guruhlarni boshqarish")

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

    def test_empty_list_when_no_unassigned_students(self):
        # Assign the only unassigned student
        StudentProfile.objects.create(user=self.student_user, group=self.group)
        self.client.force_login(self.teacher)
        response = self.client.get(reverse("add_student_to_group", kwargs={"group_id": self.group.pk}))
        self.assertContains(response, "yo'q")

