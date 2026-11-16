"""Har bir tugma bosilgandan keyin tizim tushunarli javob berishini tekshiruvchi testlar."""
from datetime import date
from decimal import Decimal

from django.contrib.messages import get_messages
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Invoice, Notification, Payment, StudentProfile, StudyGroup, User
from .test_features import make_world


def texts(response):
    return [str(m) for m in get_messages(response.wsgi_request)]


class GroupDialogTests(TestCase):
    def setUp(self):
        self.group, self.teacher, self.admin, self.parent, self.student, self.profile = make_world()
        # Rol bo'yicha administrator, lekin Django admin paneliga (is_staff) kira olmaydi.
        self.manager = User.objects.create_user("manager", password="Pass12345!x", role=User.Role.ADMIN)
        self.client.force_login(self.manager)

    def test_new_group_button_opens_in_app_dialog_instead_of_django_admin(self):
        response = self.client.get(reverse("group_management"))
        self.assertContains(response, 'data-dialog-open="group-dialog"')
        self.assertContains(response, 'id="group-dialog"')
        self.assertNotContains(response, "/admin/school/studygroup/add/")

    def test_group_is_created_and_user_lands_on_its_page(self):
        response = self.client.post(reverse("group_management"), {"name": "B2", "subject": "Matematika", "monthly_fee": "250000"})
        group = StudyGroup.objects.get(name="B2")
        self.assertRedirects(response, reverse("group_detail", args=[group.pk]))
        self.assertEqual(group.monthly_fee, Decimal("250000"))
        self.assertTrue(any("B2" in t for t in texts(response)))

    def test_duplicate_name_reopens_dialog_with_error(self):
        response = self.client.post(reverse("group_management"), {"name": "a1", "subject": "X", "monthly_fee": "0"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-open-on-load")
        self.assertContains(response, "allaqachon mavjud")

    @override_settings(MAX_STUDY_GROUPS=1)
    def test_limit_disables_button_and_rejects_post(self):
        response = self.client.get(reverse("group_management"))
        self.assertContains(response, "Guruhlar soni chegaraga yetgan")
        response = self.client.post(reverse("group_management"), {"name": "B2", "subject": "X", "monthly_fee": "0"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ko‘pi bilan 1 ta guruh")
        self.assertFalse(StudyGroup.objects.filter(name="B2").exists())

    def test_non_admin_cannot_create_group(self):
        self.client.force_login(self.teacher)
        response = self.client.post(reverse("group_management"), {"name": "B2", "subject": "X", "monthly_fee": "0"})
        self.assertEqual(response.status_code, 403)

    def test_dashboard_link_opens_dialog(self):
        response = self.client.get(reverse("group_management") + "?yangi=1")
        self.assertContains(response, "data-open-on-load")


class DashboardTests(TestCase):
    def setUp(self):
        self.group, self.teacher, self.admin, self.parent, self.student, self.profile = make_world()

    def test_teacher_group_card_shows_real_student_count(self):
        second = User.objects.create_user("s2", password="Pass12345!x", role=User.Role.STUDENT)
        StudentProfile.objects.create(user=second, group=self.group)
        self.client.force_login(self.teacher)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "2 nafar o‘quvchi")

    @override_settings(MAX_STUDY_GROUPS=7)
    def test_admin_dashboard_uses_configured_group_limit(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "Maksimal guruh soni: 7")


class RobustInputTests(TestCase):
    def setUp(self):
        self.group, self.teacher, self.admin, self.parent, self.student, self.profile = make_world()
        self.client.force_login(self.admin)

    def test_nan_payment_amount_gives_message_not_server_error(self):
        invoice = Invoice.objects.create(student=self.profile, period=date(2026, 11, 1), amount=Decimal("300000"), due_date=date(2026, 11, 10))
        for bad in ("NaN", "Infinity", "-5", "abc", ""):
            response = self.client.post(reverse("record_payment", args=[invoice.pk]), {"amount": bad, "method": "cash"})
            self.assertEqual(response.status_code, 302, bad)
            self.assertTrue(texts(response), bad)
        self.assertFalse(Payment.objects.exists())

    def test_tampered_ids_return_404_not_500(self):
        cases = [
            (reverse("teacher_assign_group", args=[self.teacher.pk]), {"group_id": "abc"}),
            (reverse("teacher_assign_group", args=[self.teacher.pk]), {"group_id": ""}),
            (reverse("group_detail", args=[self.group.pk]), {"action": "assign_teacher", "teacher_id": "x"}),
            (reverse("group_detail", args=[self.group.pk]), {"action": "assign_student", "student_id": ""}),
            (reverse("applications_list"), {"application_id": "x", "status": "new"}),
            (reverse("generate_invoices"), {"period": "2026-11", "group": "x"}),
        ]
        for url, data in cases:
            self.assertEqual(self.client.post(url, data).status_code, 404, (url, data))

    def test_assigning_teacher_twice_says_already_assigned(self):
        response = self.client.post(reverse("teacher_assign_group", args=[self.teacher.pk]), {"group_id": self.group.pk})
        self.assertTrue(any("allaqachon" in t for t in texts(response)))

    def test_generate_invoices_without_fee_explains_why_nothing_happened(self):
        StudyGroup.objects.filter(pk=self.group.pk).update(monthly_fee=0)
        response = self.client.post(reverse("generate_invoices"), {"period": "2026-11"})
        self.assertTrue(any("Hisob yaratilmadi" in t for t in texts(response)))

    def test_unknown_group_detail_action_reports_error(self):
        response = self.client.post(reverse("group_detail", args=[self.group.pk]), {"action": "nope"})
        self.assertTrue(any("aniqlanmadi" in t for t in texts(response)))


class FeedbackMessageTests(TestCase):
    def setUp(self):
        self.group, self.teacher, self.admin, self.parent, self.student, self.profile = make_world()

    def test_mark_read_confirms_result(self):
        Notification.objects.create(user=self.student, title="T")
        self.client.force_login(self.student)
        first = self.client.post(reverse("notifications_mark_read"))
        self.assertTrue(any("belgilandi" in t for t in texts(first)))
        second = self.client.post(reverse("notifications_mark_read"))
        self.assertTrue(any("yo‘q" in t for t in texts(second)))

    def test_password_reset_without_challenge_shows_visible_error(self):
        response = self.client.post(reverse("password_reset"), {
            "action": "reset_password", "code": "123456", "new_password": "Zx9!kkLmn22", "confirm_password": "Zx9!kkLmn22"})
        self.assertContains(response, "Faol tasdiqlash so‘rovi topilmadi")

    def test_password_reset_restart_clears_challenge(self):
        session = self.client.session
        session["password_reset_otp_id"] = 999
        session.save()
        response = self.client.post(reverse("password_reset"), {"action": "restart"})
        self.assertRedirects(response, reverse("password_reset"))
        self.assertNotIn("password_reset_otp_id", self.client.session)

    def test_signup_complete_without_challenge_shows_visible_error(self):
        response = self.client.post(reverse("signup"), {
            "action": "complete_signup", "code": "123456", "new_password": "Zx9!kkLmn22", "confirm_password": "Zx9!kkLmn22"})
        self.assertContains(response, "Tasdiqlash so‘rovi muddati tugagan")

    def test_signup_restart_removes_pending_account(self):
        pending = User.objects.create(username="pending", role=User.Role.STUDENT, is_active=False)
        session = self.client.session
        session["signup_user_id"] = pending.pk
        session.save()
        response = self.client.post(reverse("signup"), {"action": "restart"})
        self.assertRedirects(response, reverse("signup"))
        self.assertFalse(User.objects.filter(pk=pending.pk).exists())

    def test_close_account_verify_without_challenge_shows_visible_error(self):
        self.client.force_login(self.student)
        response = self.client.post(reverse("close_account"), {"action": "verify_code", "code": "123456"})
        self.assertContains(response, "Faol tasdiqlash so‘rovi topilmadi")

    def test_settings_forms_return_to_their_section(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse("settings_panel"))
        self.assertContains(response, 'action="/sozlamalar/#parol"')
        self.assertContains(response, 'action="/sozlamalar/#profil"')

    def test_grade_form_exposes_lesson_student_group_maps(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("grade_lesson"))
        self.assertEqual(response.context["student_groups"], {str(self.profile.pk): self.group.pk})
        self.assertContains(response, 'id="student-group-map"')

    def test_stylesheet_linked_once(self):
        response = self.client.get(reverse("login"))
        self.assertEqual(response.content.decode().count("ui-polish.css"), 1)
