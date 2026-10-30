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
        response = self.client.get(reverse("add_student_to_group", group_id=self.group.pk))
        self.assertEqual(response.status_code, 200)

    def test_other_teacher_cannot_access(self):
        self.client.force_login(self.other_teacher)
        response = self.client.get(reverse("add_student_to_group", group_id=self.group.pk))
        self.assertEqual(response.status_code, 403)

    def test_student_cannot_access(self):
        self.client.force_login(self.student_user)
        response = self.client.get(reverse("add_student_to_group", group_id=self.group.pk))
        self.assertEqual(response.status_code, 403)

    def test_unassigned_student_appears_in_list(self):
        self.client.force_login(self.teacher)
        response = self.client.get(reverse("add_student_to_group", group_id=self.group.pk))
        self.assertContains(response, "Ali Valiyev")

    def test_already_assigned_student_does_not_appear(self):
        self.client.force_login(self.teacher)
        response = self.client.get(reverse("add_student_to_group", group_id=self.group.pk))
        self.assertNotContains(response, "In Group")

    def test_non_student_does_not_appear(self):
        self.client.force_login(self.teacher)
        response = self.client.get(reverse("add_student_to_group", group_id=self.group.pk))
        self.assertNotContains(response, "Not Student")

    def test_search_filters_by_first_name(self):
        self.client.force_login(self.teacher)
        response = self.client.get(
            reverse("add_student_to_group", group_id=self.group.pk) + "?search=Ali"
        )
        self.assertContains(response, "Ali Valiyev")

    def test_search_filters_by_last_name(self):
        self.client.force_login(self.teacher)
        response = self.client.get(
            reverse("add_student_to_group", group_id=self.group.pk) + "?search=Valiyev"
        )
        self.assertContains(response, "Ali Valiyev")

    def test_successful_add_creates_student_profile(self):
        self.client.force_login(self.teacher)
        self.assertFalse(StudentProfile.objects.filter(user=self.student_user).exists())
        response = self.client.post(
            reverse("add_student_to_group", group_id=self.group.pk),
            {"student": self.student_user.pk},
        )
        self.assertRedirects(response, reverse("add_student_to_group", group_id=self.group.pk))
        self.student_user.refresh_from_db()
        self.assertTrue(hasattr(self.student_user, "student_profile"))
        profile = StudentProfile.objects.get(user=self.student_user)
        self.assertEqual(profile.group, self.group)

    def test_cannot_add_student_already_in_group(self):
        self.client.force_login(self.teacher)
        response = self.client.post(
            reverse("add_student_to_group", group_id=self.group.pk),
            {"student": self.already_in_group.pk},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "allaqachon")

    def test_cannot_add_non_student_account(self):
        self.client.force_login(self.teacher)
        response = self.client.post(
            reverse("add_student_to_group", group_id=self.group.pk),
            {"student": self.non_student.pk},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Faqat o'quvchi")

    def test_empty_list_when_no_unassigned_students(self):
        # Assign the only unassigned student
        StudentProfile.objects.create(user=self.student_user, group=self.group)
        self.client.force_login(self.teacher)
        response = self.client.get(reverse("add_student_to_group", group_id=self.group.pk))
        self.assertContains(response, "yo'q")

