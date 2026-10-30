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
from .models import User, StudyGroup, StudentProfile, Lesson, GradeReason, GradeRecord, Attendance, PhoneOTP
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
        response = self.client.post(reverse("close_account"), {"action": "close_account", "code": code})
        self.assertRedirects(response, reverse("home"))
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)
        self.assertTrue(StudentProfile.objects.filter(pk=profile.pk).exists())

    def test_admin_cannot_close_account_from_self_service(self):
        admin_user = User.objects.create_user("phone_admin", password="StrongPassword123!", role=User.Role.ADMIN)
        self.client.force_login(admin_user)
        self.assertEqual(self.client.get(reverse("close_account")).status_code, 403)

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
