from django.test import TestCase, Client
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from .models import User, StudyGroup, StudentProfile, Lesson, GradeReason, GradeRecord, Attendance
from .forms import GradeRecordForm

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
