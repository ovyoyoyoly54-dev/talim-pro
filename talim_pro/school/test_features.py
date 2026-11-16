import base64
import hashlib
import io
import json
import time
from datetime import date, timedelta
from decimal import Decimal

import shutil
import tempfile

import pyotp
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import billing, twofactor
from .models import (
    AuditLog, Course, EnrollmentApplication, Homework, HomeworkSubmission, Invoice, Lesson, Notification,
    Payment, PushSubscription, StudentProfile, StudyGroup, TwoFactorDevice, User, Attendance, GradeRecord,
)


def make_world():
    group = StudyGroup.objects.create(name="A1", subject="Ingliz tili", monthly_fee=Decimal("300000"))
    teacher = User.objects.create_user("teacher1", password="Pass12345!x", role=User.Role.TEACHER, first_name="Ali", last_name="Valiyev")
    group.teachers.add(teacher)
    admin_user = User.objects.create_user("admin1", password="Pass12345!x", role=User.Role.ADMIN, is_staff=True)
    parent = User.objects.create_user("parent1", password="Pass12345!x", role=User.Role.PARENT)
    student_user = User.objects.create_user("student1", password="Pass12345!x", role=User.Role.STUDENT, first_name="Vali", last_name="Aliyev")
    profile = StudentProfile.objects.create(user=student_user, group=group, parent=parent)
    return group, teacher, admin_user, parent, student_user, profile


class BillingTests(TestCase):
    def setUp(self):
        self.group, self.teacher, self.admin, self.parent, self.student, self.profile = make_world()
        self.period = date(2026, 11, 1)

    def test_generate_invoices_is_idempotent_and_skips_free_groups(self):
        free = StudyGroup.objects.create(name="Free", subject="X")
        other = User.objects.create_user("s2", password="Pass12345!x", role=User.Role.STUDENT)
        StudentProfile.objects.create(user=other, group=free)
        created, skipped = billing.generate_invoices(self.period)
        self.assertEqual((len(created), skipped), (1, 0))
        created, skipped = billing.generate_invoices(self.period)
        self.assertEqual((len(created), skipped), (0, 1))
        self.assertEqual(Invoice.objects.get().amount, Decimal("300000"))

    def test_partial_then_full_payment_updates_status(self):
        invoice = Invoice.objects.create(student=self.profile, period=self.period, amount=Decimal("300000"), due_date=date(2026, 11, 10))
        Payment.objects.create(invoice=invoice, amount=Decimal("100000"), method="cash").mark_completed()
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Invoice.Status.PARTIAL)
        self.assertEqual(invoice.balance, Decimal("200000"))
        Payment.objects.create(invoice=invoice, amount=Decimal("200000"), method="card").mark_completed()
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Invoice.Status.PAID)

    def test_debtors_only_lists_overdue_unpaid(self):
        Invoice.objects.create(student=self.profile, period=date(2020, 1, 1), amount=Decimal("100"), due_date=date(2020, 1, 10))
        Invoice.objects.create(student=self.profile, period=date(2099, 1, 1), amount=Decimal("500"), due_date=date(2099, 1, 10))
        rows = billing.debtors()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["debt"], Decimal("100"))

    def test_admin_records_manual_payment_and_amount_is_validated(self):
        invoice = Invoice.objects.create(student=self.profile, period=self.period, amount=Decimal("300000"), due_date=date(2026, 11, 10))
        self.client.force_login(self.admin)
        url = reverse("record_payment", args=[invoice.pk])
        self.client.post(url, {"amount": "999999", "method": "cash"})
        self.assertEqual(Payment.objects.count(), 0)
        self.client.post(url, {"amount": "300000", "method": "click"})  # onlayn usulni qo'lda kiritib bo'lmaydi
        self.assertEqual(Payment.objects.count(), 0)
        self.client.post(url, {"amount": "300000", "method": "cash"})
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Invoice.Status.PAID)
        self.assertTrue(Notification.objects.filter(user=self.parent, title__icontains="to").exists())

    def test_only_admin_manages_payments_and_family_sees_own(self):
        invoice = Invoice.objects.create(student=self.profile, period=self.period, amount=Decimal("300000"), due_date=date(2026, 11, 10))
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(reverse("payments_overview")).status_code, 403)
        self.assertEqual(self.client.post(reverse("record_payment", args=[invoice.pk]), {"amount": "1", "method": "cash"}).status_code, 403)
        self.client.force_login(self.parent)
        response = self.client.get(reverse("payments_overview"))
        self.assertContains(response, "300000")
        self.assertEqual(self.client.get(reverse("debtors_list")).status_code, 403)

    def test_generate_view_creates_invoices(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("generate_invoices"), {"period": "2026-11"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Invoice.objects.filter(period=self.period).count(), 1)
        self.assertEqual(self.client.get(reverse("payments_overview") + "?period=2026-11").status_code, 200)
        self.assertEqual(self.client.get(reverse("debtors_list")).status_code, 200)

    def test_pay_links_are_built_only_when_configured(self):
        invoice = Invoice.objects.create(student=self.profile, period=self.period, amount=Decimal("300000"), due_date=date(2026, 11, 10))
        self.assertEqual(billing.payme_pay_url(invoice), "")
        with override_settings(PAYME_MERCHANT_ID="mid", PAYME_TEST=True):
            url = billing.payme_pay_url(invoice)
        self.assertTrue(url.startswith("https://test.paycom.uz/"))
        decoded = base64.b64decode(url.rsplit("/", 1)[1]).decode()
        self.assertIn(f"ac.invoice_id={invoice.pk}", decoded)
        self.assertIn("a=30000000", decoded)


CLICK = dict(CLICK_SERVICE_ID="111", CLICK_MERCHANT_ID="222", CLICK_SECRET_KEY="secret")


@override_settings(**CLICK)
class ClickTests(TestCase):
    def setUp(self):
        *_, self.profile = make_world()
        self.invoice = Invoice.objects.create(student=self.profile, period=date(2026, 11, 1), amount=Decimal("300000"), due_date=date(2026, 11, 10))

    def call(self, action, **extra):
        data = {"click_trans_id": "555", "service_id": "111", "merchant_trans_id": str(self.invoice.pk),
                "amount": "300000.00", "action": str(action), "sign_time": "2026-11-16 10:00:00", "error": "0"}
        data.update(extra)
        if "sign_string" not in data:
            data["sign_string"] = twofactor_free_sign(data, complete=action == 1)
        return self.client.post(reverse("click_webhook"), data).json()

    def test_prepare_then_complete_marks_paid(self):
        prepared = self.call(0)
        self.assertEqual(prepared["error"], 0)
        done = self.call(1, merchant_prepare_id=str(prepared["merchant_prepare_id"]))
        self.assertEqual(done["error"], 0)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, Invoice.Status.PAID)
        # Takroriy complete — "already paid"
        again = self.call(1, merchant_prepare_id=str(prepared["merchant_prepare_id"]))
        self.assertEqual(again["error"], -4)

    def test_bad_signature_wrong_amount_and_unknown_invoice(self):
        self.assertEqual(self.call(0, sign_string="0" * 32)["error"], -1)
        self.assertEqual(self.call(0, amount="1.00")["error"], -2)
        self.assertEqual(self.call(0, merchant_trans_id="999999")["error"], -5)
        self.assertEqual(Payment.objects.count(), 0)

    def test_click_cancel_on_complete_with_error(self):
        prepared = self.call(0)
        done = self.call(1, merchant_prepare_id=str(prepared["merchant_prepare_id"]), error="-5017")
        self.assertEqual(done["error"], -9)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, Invoice.Status.UNPAID)

    @override_settings(CLICK_SECRET_KEY="")
    def test_unconfigured_click_rejects(self):
        self.assertEqual(self.call(0, sign_string="x")["error"], -7)

    def test_get_not_allowed(self):
        self.assertEqual(self.client.get(reverse("click_webhook")).status_code, 405)


def twofactor_free_sign(data, *, complete):
    parts = [data["click_trans_id"], data["service_id"], "secret", data["merchant_trans_id"]]
    if complete:
        parts.append(data.get("merchant_prepare_id", ""))
    parts += [data["amount"], data["action"], data["sign_time"]]
    return hashlib.md5("".join(parts).encode()).hexdigest()


@override_settings(PAYME_KEY="paykey", PAYME_MERCHANT_ID="mid")
class PaymeTests(TestCase):
    def setUp(self):
        *_, self.profile = make_world()
        self.invoice = Invoice.objects.create(student=self.profile, period=date(2026, 11, 1), amount=Decimal("300000"), due_date=date(2026, 11, 10))
        self.auth = "Basic " + base64.b64encode(b"Paycom:paykey").decode()

    def rpc(self, method, params, auth=True):
        headers = {"HTTP_AUTHORIZATION": self.auth} if auth else {}
        response = self.client.post(reverse("payme_webhook"), json.dumps({"id": 1, "method": method, "params": params}),
                                    content_type="application/json", **headers)
        return response.json()

    def account(self, **kw):
        base = {"amount": 30000000, "account": {"invoice_id": self.invoice.pk}}
        base.update(kw)
        return base

    def test_requires_auth(self):
        self.assertEqual(self.rpc("CheckPerformTransaction", self.account(), auth=False)["error"]["code"], -32504)

    def test_check_perform_errors(self):
        self.assertEqual(self.rpc("CheckPerformTransaction", self.account())["result"], {"allow": True})
        self.assertEqual(self.rpc("CheckPerformTransaction", self.account(amount=100))["error"]["code"], -31001)
        self.assertEqual(self.rpc("CheckPerformTransaction", {"amount": 1, "account": {"invoice_id": 9999}})["error"]["code"], -31050)
        self.assertEqual(self.rpc("NoSuchMethod", {})["error"]["code"], -32601)

    def test_full_lifecycle_create_perform_check_cancel(self):
        now = int(time.time() * 1000)
        created = self.rpc("CreateTransaction", self.account(id="tx1", time=now))["result"]
        self.assertEqual(created["state"], 1)
        # Takroriy create — o'sha tranzaksiya
        self.assertEqual(self.rpc("CreateTransaction", self.account(id="tx1", time=now))["result"]["transaction"], created["transaction"])
        # Boshqa tranzaksiya shu hisobga — band
        self.assertEqual(self.rpc("CreateTransaction", self.account(id="tx2", time=now))["error"]["code"], -31099)
        performed = self.rpc("PerformTransaction", {"id": "tx1"})["result"]
        self.assertEqual(performed["state"], 2)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, Invoice.Status.PAID)
        self.assertEqual(self.rpc("PerformTransaction", {"id": "tx1"})["result"]["perform_time"], performed["perform_time"])
        self.assertEqual(self.rpc("CheckTransaction", {"id": "tx1"})["result"]["state"], 2)
        self.assertEqual(self.rpc("CheckPerformTransaction", self.account())["error"]["code"], -31051)
        cancelled = self.rpc("CancelTransaction", {"id": "tx1", "reason": 5})["result"]
        self.assertEqual(cancelled["state"], -2)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, Invoice.Status.UNPAID)
        statement = self.rpc("GetStatement", {"from": now - 1000, "to": now + 1000})["result"]["transactions"]
        self.assertEqual(statement[0]["id"], "tx1")

    def test_cancel_before_perform_and_unknown_transaction(self):
        now = int(time.time() * 1000)
        self.rpc("CreateTransaction", self.account(id="tx9", time=now))
        self.assertEqual(self.rpc("CancelTransaction", {"id": "tx9", "reason": 3})["result"]["state"], -1)
        self.assertEqual(self.rpc("PerformTransaction", {"id": "tx9"})["error"]["code"], -31008)
        self.assertEqual(self.rpc("CheckTransaction", {"id": "nope"})["error"]["code"], -31003)

    def test_expired_transaction_is_cancelled_on_perform(self):
        old = int(time.time() * 1000) - 13 * 3600 * 1000
        self.rpc("CreateTransaction", self.account(id="old", time=old))
        self.assertEqual(self.rpc("PerformTransaction", {"id": "old"})["error"]["code"], -31008)
        self.assertEqual(Payment.objects.get(external_id="old").status, Payment.Status.CANCELLED)


class HomeworkTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._media = tempfile.mkdtemp()
        cls._override = override_settings(MEDIA_ROOT=cls._media)
        cls._override.enable()

    @classmethod
    def tearDownClass(cls):
        cls._override.disable()
        shutil.rmtree(cls._media, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.group, self.teacher, self.admin, self.parent, self.student, self.profile = make_world()
        self.outsider = User.objects.create_user("out1", password="Pass12345!x", role=User.Role.STUDENT)
        other = StudyGroup.objects.create(name="B1", subject="Y")
        StudentProfile.objects.create(user=self.outsider, group=other)
        self.homework = Homework.objects.create(
            group=self.group, title="Unit 1", description="Yozing", teacher=self.teacher,
            due_at=timezone.now() + timedelta(days=2),
        )

    def test_teacher_creates_and_students_are_notified(self):
        self.client.force_login(self.teacher)
        due = (timezone.localtime() + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M")
        response = self.client.post(reverse("homework_create"), {
            "group": self.group.pk, "title": "Unit 2", "description": "x", "due_at": due,
            "attachment": SimpleUploadedFile("task.pdf", b"%PDF-1.4 test"),
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Homework.objects.filter(title="Unit 2", teacher=self.teacher).exists())
        self.assertTrue(Notification.objects.filter(user=self.student, title__icontains="vazifa").exists())

    def test_rejects_past_due_and_bad_extension(self):
        self.client.force_login(self.teacher)
        past = (timezone.localtime() - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
        response = self.client.post(reverse("homework_create"), {"group": self.group.pk, "title": "T", "due_at": past})
        self.assertEqual(response.status_code, 200)
        future = (timezone.localtime() + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
        response = self.client.post(reverse("homework_create"), {
            "group": self.group.pk, "title": "T", "due_at": future,
            "attachment": SimpleUploadedFile("evil.exe", b"MZ"),
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Homework.objects.filter(title="T").exists())

    def test_student_submits_and_teacher_grades(self):
        self.client.force_login(self.student)
        response = self.client.post(reverse("homework_detail", args=[self.homework.pk]), {
            "text": "Mening javobim", "file": SimpleUploadedFile("a.txt", b"hello")})
        self.assertEqual(response.status_code, 302)
        submission = HomeworkSubmission.objects.get()
        self.assertFalse(submission.is_late)
        self.client.force_login(self.teacher)
        self.client.post(reverse("homework_detail", args=[self.homework.pk]), {
            "action": "grade", "submission_id": submission.pk, "score": "9", "feedback": "Yaxshi"})
        submission.refresh_from_db()
        self.assertEqual(submission.score, 9)
        self.assertEqual(submission.graded_by, self.teacher)
        # 11 — noto'g'ri baho
        self.client.post(reverse("homework_detail", args=[self.homework.pk]), {
            "action": "grade", "submission_id": submission.pk, "score": "11"})
        submission.refresh_from_db()
        self.assertEqual(submission.score, 9)
        # baholangan javobni o'quvchi o'zgartira olmaydi
        self.client.force_login(self.student)
        self.client.post(reverse("homework_detail", args=[self.homework.pk]), {"text": "o'zgartirdim"})
        submission.refresh_from_db()
        self.assertEqual(submission.text, "Mening javobim")

    def test_late_submission_is_flagged(self):
        self.homework.due_at = timezone.now() - timedelta(hours=1)
        self.homework.save()
        self.client.force_login(self.student)
        self.client.post(reverse("homework_detail", args=[self.homework.pk]), {"text": "kech"})
        self.assertTrue(HomeworkSubmission.objects.get().is_late)

    def test_access_control(self):
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(reverse("homework_detail", args=[self.homework.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("homework_detail", args=[self.homework.pk]), {"text": "x"}).status_code, 404)
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(reverse("homework_create")).status_code, 403)

    def test_answer_file_only_for_owner_teacher_and_parent(self):
        submission = HomeworkSubmission.objects.create(
            homework=self.homework, student=self.profile, text="x", file=SimpleUploadedFile("ans.txt", b"secret"))
        url = reverse("homework_answer_file", args=[submission.pk])
        for user, code in ((self.student, 200), (self.teacher, 200), (self.parent, 200), (self.outsider, 403)):
            self.client.force_login(user)
            self.assertEqual(self.client.get(url).status_code, code, user.username)


class NotificationTests(TestCase):
    def setUp(self):
        *_, self.student, self.profile = make_world()

    def test_list_mark_read_and_unread_badge(self):
        Notification.objects.create(user=self.student, title="Salom")
        self.client.force_login(self.student)
        self.assertContains(self.client.get(reverse("dashboard")), "pill-red")
        self.assertContains(self.client.get(reverse("notification_list")), "Salom")
        self.client.post(reverse("notifications_mark_read"))
        self.assertFalse(Notification.objects.filter(user=self.student, read_at__isnull=True).exists())

    def test_push_subscribe_requires_configuration_and_valid_payload(self):
        self.client.force_login(self.student)
        payload = {"endpoint": "https://push.example/abc", "keys": {"p256dh": "k", "auth": "a"}}
        response = self.client.post(reverse("push_subscribe"), json.dumps(payload), content_type="application/json")
        self.assertEqual(response.status_code, 503)
        with override_settings(VAPID_PUBLIC_KEY="pub", VAPID_PRIVATE_KEY="priv"):
            bad = self.client.post(reverse("push_subscribe"), json.dumps({"endpoint": "http://x", "keys": {}}), content_type="application/json")
            self.assertEqual(bad.status_code, 400)
            ok = self.client.post(reverse("push_subscribe"), json.dumps(payload), content_type="application/json")
            self.assertEqual(ok.status_code, 200)
            self.assertEqual(PushSubscription.objects.filter(user=self.student).count(), 1)
            self.client.post(reverse("push_unsubscribe"), json.dumps({"endpoint": payload["endpoint"]}), content_type="application/json")
            self.assertEqual(PushSubscription.objects.count(), 0)

    def test_push_replaces_sms_for_family(self):
        from unittest.mock import patch
        from .notifications import notify_family
        self.profile.parent_phone = "+998901234567"
        self.profile.save()
        with patch("school.sms.send_parent_sms") as sms:
            notify_family(self.profile, "t", "b", sms_body="sms")
            self.assertTrue(sms.called)  # push yo'q — SMS zaxira
            sms.reset_mock()
            PushSubscription.objects.create(user=self.student, endpoint="https://p/1", p256dh="k", auth="a")
            with override_settings(VAPID_PUBLIC_KEY="pub", VAPID_PRIVATE_KEY="priv"), patch("school.notifications._send_push", return_value=True):
                notify_family(self.profile, "t", "b", sms_body="sms")
            self.assertFalse(sms.called)  # push bor — SMS yuborilmaydi


class PublicPagesTests(TestCase):
    def setUp(self):
        self.course = Course.objects.create(title="IELTS", slug="ielts", summary="Qisqa", price=Decimal("500000"), duration="6 oy")
        Course.objects.create(title="Yashirin", slug="hidden", summary="x", price=1, is_published=False)

    def test_pages_render_and_sitemap_lists_published_courses(self):
        for name, args in (("courses_list", []), ("pricing", []), ("apply", []), ("course_detail", ["ielts"])):
            response = self.client.get(reverse(name, args=args))
            self.assertEqual(response.status_code, 200, name)
            self.assertContains(response, 'content="index,follow"')
        self.assertEqual(self.client.get(reverse("course_detail", args=["hidden"])).status_code, 404)
        sitemap = self.client.get(reverse("sitemap_xml")).content
        self.assertIn(b"/kurslar/ielts/", sitemap)
        self.assertNotIn(b"/kurslar/hidden/", sitemap)
        self.assertContains(self.client.get(reverse("pricing")), "500000")

    def test_application_flow_honeypot_and_rate_limit(self):
        admin_user = User.objects.create_user("adm", password="Pass12345!x", role=User.Role.ADMIN)
        data = {"full_name": "Test Odam", "phone": "90 123 45 67", "course": self.course.pk, "message": ""}
        self.assertRedirects(self.client.post(reverse("apply"), data), reverse("apply_done"))
        application = EnrollmentApplication.objects.get()
        self.assertEqual(application.phone, "+998901234567")
        self.assertTrue(Notification.objects.filter(user=admin_user).exists())
        self.assertEqual(self.client.post(reverse("apply"), {**data, "website": "spam.com"}).status_code, 200)
        self.assertEqual(EnrollmentApplication.objects.count(), 1)
        self.assertEqual(self.client.post(reverse("apply"), {**data, "phone": "abc"}).status_code, 200)
        for _ in range(6):
            self.client.post(reverse("apply"), data)
        self.assertEqual(EnrollmentApplication.objects.count(), 5)

    def test_applications_list_is_admin_only(self):
        admin_user = User.objects.create_user("adm", password="Pass12345!x", role=User.Role.ADMIN)
        EnrollmentApplication.objects.create(full_name="A", phone="+998901112233")
        self.assertEqual(self.client.get(reverse("applications_list")).status_code, 302)
        student = User.objects.create_user("st", password="Pass12345!x", role=User.Role.STUDENT)
        self.client.force_login(student)
        self.assertEqual(self.client.get(reverse("applications_list")).status_code, 403)
        self.client.force_login(admin_user)
        application = EnrollmentApplication.objects.get()
        self.client.post(reverse("applications_list"), {"application_id": application.pk, "status": "contacted"})
        application.refresh_from_db()
        self.assertEqual(application.status, "contacted")


class ReportTests(TestCase):
    def setUp(self):
        self.group, self.teacher, self.admin, self.parent, self.student, self.profile = make_world()
        lesson = Lesson.objects.create(group=self.group, title="L1", starts_at=timezone.now() - timedelta(days=1), teacher=self.teacher, room="1")
        Attendance.objects.create(lesson=lesson, student=self.profile, status="present", teacher=self.teacher)
        reason = None
        GradeRecord.objects.create(lesson=lesson, student=self.profile, score=9, teacher=self.teacher)

    def test_excel_and_pdf_exports(self):
        from openpyxl import load_workbook
        self.client.force_login(self.admin)
        for name in ("attendance_report", "ranking_report"):
            xlsx = self.client.get(reverse(name), {"format": "xlsx"})
            self.assertEqual(xlsx.status_code, 200)
            self.assertIn("spreadsheetml", xlsx["Content-Type"])
            sheet = load_workbook(io.BytesIO(xlsx.content)).active
            self.assertEqual(sheet.max_row, 2)
            pdf = self.client.get(reverse(name), {"format": "pdf"})
            self.assertEqual(pdf["Content-Type"], "application/pdf")
            self.assertTrue(pdf.content.startswith(b"%PDF"))
        self.assertEqual(self.client.get(reverse("attendance_report"), {"format": "csv"}).status_code, 404)

    def test_excel_formula_injection_is_neutralised(self):
        self.student.first_name = "=HYPERLINK(\"http://evil\")"
        self.student.save()
        from openpyxl import load_workbook
        self.client.force_login(self.admin)
        sheet = load_workbook(io.BytesIO(self.client.get(reverse("ranking_report"), {"format": "xlsx"}).content)).active
        self.assertTrue(str(sheet["B2"].value).startswith("'="))

    def test_access_scope(self):
        other_group = StudyGroup.objects.create(name="Z", subject="z")
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(reverse("ranking_report"), {"group": other_group.pk}).status_code, 403)
        self.assertEqual(self.client.get(reverse("ranking_report"), {"group": self.group.pk}).status_code, 200)
        self.assertEqual(self.client.get(reverse("ranking_report"), {"group": "abc"}).status_code, 404)
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(reverse("reports_home")).status_code, 403)
        self.assertEqual(self.client.get(reverse("attendance_report")).status_code, 403)

    def test_attendance_percentage(self):
        from .views_reports import attendance_rows
        rows = attendance_rows(StudyGroup.objects.all())
        self.assertEqual(rows[0][2:], [1, 1, 0, 0, 100.0])


@override_settings(ADMIN_2FA_REQUIRED=True)
class TwoFactorTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_user("boss", password="Pass12345!x", role=User.Role.ADMIN, is_staff=True)
        self.student = User.objects.create_user("stud", password="Pass12345!x", role=User.Role.STUDENT)

    def login(self, user="boss"):
        self.client.logout()
        self.assertTrue(self.client.login(username=user, password="Pass12345!x"))

    def test_admin_is_forced_into_setup_but_students_are_not(self):
        self.login()
        response = self.client.get(reverse("dashboard"))
        self.assertRedirects(response, f"{reverse('two_factor_setup')}?next={reverse('dashboard')}", fetch_redirect_response=False)
        self.assertEqual(self.client.get("/admin/").status_code, 302)
        self.login("stud")
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)

    def test_setup_then_login_requires_code_and_replay_is_rejected(self):
        self.login()
        page = self.client.get(reverse("two_factor_setup"))
        self.assertContains(page, "data:image/png;base64")
        secret = self.client.session["2fa_pending_secret"]
        code = pyotp.TOTP(secret).now()
        self.assertEqual(self.client.post(reverse("two_factor_setup"), {"code": "000000"}).status_code, 200)
        done = self.client.post(reverse("two_factor_setup"), {"code": code})
        self.assertContains(done, "<code>")  # zaxira kodlar ko'rsatildi
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)
        # yangi sessiya: kod so'raladi
        self.login()
        self.assertRedirects(self.client.get(reverse("dashboard")), f"{reverse('two_factor_verify')}?next={reverse('dashboard')}", fetch_redirect_response=False)
        # setup vaqtida ishlatilgan kod qayta qabul qilinmaydi
        self.client.post(reverse("two_factor_verify"), {"code": code})
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 302)
        device = TwoFactorDevice.objects.get(user=self.admin)
        device.last_counter = 0
        device.save()
        self.client.post(reverse("two_factor_verify"), {"code": pyotp.TOTP(secret).now()})
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)

    def test_backup_code_works_once_and_lockout_after_failures(self):
        secret = twofactor.new_secret()
        codes, hashes = twofactor.make_backup_codes()
        TwoFactorDevice.objects.create(user=self.admin, secret=secret, confirmed=True, backup_code_hashes=hashes)
        self.login()
        self.client.post(reverse("two_factor_verify"), {"code": codes[0]})
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)
        self.login()
        self.client.post(reverse("two_factor_verify"), {"code": codes[0]})
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 302)
        for _ in range(5):
            self.client.post(reverse("two_factor_verify"), {"code": "111111"})
        # bloklangandan keyin to'g'ri kod ham qabul qilinmaydi
        self.client.post(reverse("two_factor_verify"), {"code": codes[1]})
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 302)

    def test_next_redirect_is_not_open(self):
        TwoFactorDevice.objects.create(user=self.admin, secret=twofactor.new_secret(), confirmed=True)
        self.login()
        device = TwoFactorDevice.objects.get(user=self.admin)
        code = pyotp.TOTP(device.secret).now()
        response = self.client.post(reverse("two_factor_verify"), {"code": code, "next": "https://evil.example/"})
        self.assertRedirects(response, reverse("dashboard"), fetch_redirect_response=False)

    def test_reset_command_removes_device(self):
        from django.core.management import call_command
        TwoFactorDevice.objects.create(user=self.admin, secret="X", confirmed=True)
        call_command("reset_2fa", "boss", stdout=io.StringIO())
        self.assertFalse(TwoFactorDevice.objects.exists())


class AuditLogTests(TestCase):
    def setUp(self):
        self.group, self.teacher, self.admin, *_ = make_world()
        self.client.force_login(self.admin)

    def test_web_changes_are_logged_with_old_and_new_values_without_secrets(self):
        self.client.post(reverse("settings_panel"), {"action": "account_settings", "username": "admin1", "first_name": "Yangi", "last_name": "", "email": "", "phone": ""})
        entry = AuditLog.objects.filter(model="User", action="update").first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.username, "admin1")
        self.assertEqual(entry.changes["first_name"], ["", "Yangi"])
        self.assertNotIn("password", entry.changes)

    def test_no_logging_outside_requests_and_login_events_are_recorded(self):
        before = AuditLog.objects.count()
        StudyGroup.objects.create(name="NoLog", subject="x")
        self.assertEqual(AuditLog.objects.count(), before)
        Client().login(username="admin1", password="Pass12345!x")
        Client().post(reverse("login"), {"username": "admin1", "password": "wrong"})
        self.assertTrue(AuditLog.objects.filter(action="login_failed", username="admin1").exists())

    def test_audit_admin_is_read_only(self):
        from django.contrib import admin as dj_admin
        from django.test import RequestFactory
        model_admin = dj_admin.site._registry[AuditLog]
        request = RequestFactory().get("/")
        request.user = self.admin
        self.assertFalse(model_admin.has_add_permission(request))
        self.assertFalse(model_admin.has_change_permission(request))
        self.assertFalse(model_admin.has_delete_permission(request))


class LanguageTests(TestCase):
    def test_switch_to_russian_changes_pages(self):
        self.assertContains(self.client.get(reverse("courses_list")), "Bizning kurslar")
        self.client.post(reverse("set_language"), {"language": "ru", "next": "/kurslar/"})
        response = self.client.get(reverse("courses_list"))
        self.assertContains(response, "Наши курсы")
        self.assertContains(response, 'lang="ru"')
        self.client.post(reverse("set_language"), {"language": "uz", "next": "/kurslar/"})
        self.assertContains(self.client.get(reverse("courses_list")), "Bizning kurslar")
