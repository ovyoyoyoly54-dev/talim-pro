"""Dars jurnali (davomat/bahoni tuzatish), xonalar izolyatsiyasi va uyga vazifada sinf tanlash."""
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Attendance, AuditLog, GradeReason, GradeRecord, Lesson, StudentProfile, StudyGroup, User
from .test_features import make_world


class JournalTests(TestCase):
    def setUp(self):
        self.group, self.teacher, self.admin, self.parent, self.student, self.profile = make_world()
        self.lesson = Lesson.objects.create(group=self.group, title="Dars 1", teacher=self.teacher,
                                            starts_at=timezone.now() + timedelta(days=1))
        self.reason = GradeReason.objects.create(title="Uyga vazifa qilinmagan")

    def test_teacher_corrects_attendance_for_whole_group(self):
        self.client.force_login(self.teacher)
        key = f"attendance_{self.profile.pk}"
        self.client.post(reverse("lesson_journal", args=[self.lesson.pk]), {key: "absent"})
        self.assertEqual(Attendance.objects.get().status, "absent")
        self.client.post(reverse("lesson_journal", args=[self.lesson.pk]), {key: "present"})
        self.assertEqual(Attendance.objects.get().status, "present")

    def test_grade_correction_is_logged_and_shown(self):
        self.client.force_login(self.teacher)
        data = {"lesson": self.lesson.pk, "student": self.profile.pk, "score": 5,
                "reasons": [self.reason.pk], "attendance": "present"}
        self.client.post(reverse("grade_lesson"), data)
        data["score"] = 9
        data["reasons"] = []
        self.client.post(reverse("grade_lesson"), data)
        self.assertEqual(GradeRecord.objects.get().score, 9)
        self.assertTrue(AuditLog.objects.filter(model="GradeRecord", action="update").exists())
        page = self.client.get(reverse("lesson_journal", args=[self.lesson.pk]))
        self.assertContains(page, "tuzatilgan 1 marta")
        self.assertContains(page, "oldingisi: 5")

    def test_correction_form_is_prefilled(self):
        self.client.force_login(self.teacher)
        self.client.post(reverse("grade_lesson"), {"lesson": self.lesson.pk, "student": self.profile.pk,
                                                    "score": 10, "attendance": "late"})
        page = self.client.get(f"{reverse('grade_lesson')}?lesson={self.lesson.pk}&student={self.profile.pk}")
        self.assertEqual(page.context["form"].initial["score"], 10)
        self.assertEqual(page.context["form"].initial["attendance"], "late")

    def test_other_teacher_student_and_parent_cannot_open_journal(self):
        other = User.objects.create_user("t2", password="Pass12345!x", role=User.Role.TEACHER)
        url = reverse("lesson_journal", args=[self.lesson.pk])
        for user in (other, self.student, self.parent):
            self.client.force_login(user)
            self.assertIn(self.client.get(url).status_code, (403, 404))
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(url).status_code, 200)


class RoomIsolationTests(TestCase):
    def test_student_sees_only_own_room_data(self):
        group, teacher, admin_user, parent, student, profile = make_world()
        other_group = StudyGroup.objects.create(name="B1", subject="Mat")
        other_group.teachers.add(teacher)
        other_user = User.objects.create_user("s2", password="Pass12345!x", role=User.Role.STUDENT, first_name="Boshqa")
        StudentProfile.objects.create(user=other_user, group=other_group)
        Lesson.objects.create(group=other_group, title="Boshqa dars", teacher=teacher,
                              starts_at=timezone.now() + timedelta(days=1))
        self.client.force_login(student)
        self.assertNotContains(self.client.get(reverse("schedule")), "Boshqa dars")
        self.assertNotContains(self.client.get(reverse("ranking")), "Boshqa")


class HomeworkGroupPickerTests(TestCase):
    def setUp(self):
        self.group, self.teacher, self.admin, self.parent, self.student, self.profile = make_world()

    def test_single_group_teacher_goes_straight_to_list(self):
        self.client.force_login(self.teacher)
        self.assertTemplateUsed(self.client.get(reverse("homework_list")), "school/homework_list.html")

    def test_two_group_teacher_is_asked_which_class(self):
        second = StudyGroup.objects.create(name="B1", subject="Mat")
        second.teachers.add(self.teacher)
        self.client.force_login(self.teacher)
        page = self.client.get(reverse("homework_list"))
        self.assertTemplateUsed(page, "school/homework_group_picker.html")
        self.assertContains(page, "Qaysi sinf uchun?")
        chosen = self.client.get(f"{reverse('homework_list')}?group={second.pk}")
        self.assertTemplateUsed(chosen, "school/homework_list.html")
        self.assertEqual(chosen.context["selected_group"], second)

    def test_student_always_sees_homework_section(self):
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(reverse("homework_list")).status_code, 200)


class CourseRoomTests(TestCase):
    def setUp(self):
        self.group, self.teacher, self.admin, self.parent, self.student, self.profile = make_world()
        self.other = StudyGroup.objects.create(name="B1", subject="Mat")
        self.other_teacher = User.objects.create_user("t2", password="Pass12345!x", role=User.Role.TEACHER)
        self.other.teachers.add(self.other_teacher)

    def test_rooms_are_unlimited_by_default(self):
        for i in range(8):
            StudyGroup.objects.create(name=f"Xona {i}", subject="X")
        self.assertEqual(StudyGroup.objects.count(), 10)

    def test_room_page_access_by_role(self):
        url = reverse("room_detail", args=[self.group.pk])
        for user, code in ((self.teacher, 200), (self.student, 200), (self.parent, 200),
                           (self.other_teacher, 403)):
            self.client.force_login(user)
            self.assertEqual(self.client.get(url).status_code, code, user.username)
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(reverse("room_detail", args=[self.other.pk])).status_code, 403)
        self.client.force_login(self.parent)
        self.assertEqual(self.client.get(reverse("room_detail", args=[self.other.pk])).status_code, 403)
        self.client.force_login(self.admin)
        self.assertRedirects(self.client.get(url), reverse("group_detail", args=[self.group.pk]))

    def test_sidebar_shows_only_own_rooms(self):
        self.client.force_login(self.student)
        page = self.client.get(reverse("dashboard"))
        self.assertContains(page, "MENING XONAM")
        self.assertContains(page, reverse("room_detail", args=[self.group.pk]))
        self.assertNotContains(page, reverse("room_detail", args=[self.other.pk]))

    def test_admin_sidebar_lists_every_room_and_add_link(self):
        self.client.force_login(self.admin)
        page = self.client.get(reverse("dashboard"))
        self.assertContains(page, "KURS XONALAR")
        self.assertContains(page, reverse("group_detail", args=[self.other.pk]))
        self.assertContains(page, f'{reverse("group_management")}?yangi=1')
        opened = self.client.get(f'{reverse("group_management")}?yangi=1')
        self.assertContains(opened, "data-open-on-load")

    def test_active_section_is_open_and_others_collapsed(self):
        self.client.force_login(self.teacher)
        page = self.client.get(reverse("homework_list"))
        self.assertContains(page, 'id="nav-learning" aria-expanded="true"')
        self.assertContains(page, 'id="nav-main" aria-expanded="false"')
