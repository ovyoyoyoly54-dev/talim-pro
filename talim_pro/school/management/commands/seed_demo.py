from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from school.models import User, StudyGroup, StudentProfile, Lesson, GradeReason

class Command(BaseCommand):
    help = "Sinov uchun namuna guruh, akkauntlar va sabablarni yaratadi."

    def handle(self, *args, **options):
        admin, _ = User.objects.get_or_create(username="admin_demo", defaults={"role": User.Role.ADMIN, "first_name": "Demo", "last_name": "Administrator", "is_staff": True, "is_superuser": True})
        admin.set_password("ChangeMe123!")
        admin.save()
        teacher, _ = User.objects.get_or_create(username="teacher_demo", defaults={"role": User.Role.TEACHER, "first_name": "Demo", "last_name": "O‘qituvchi"})
        teacher.set_password("ChangeMe123!")
        teacher.save()
        parent, _ = User.objects.get_or_create(username="parent_demo", defaults={"role": User.Role.PARENT, "first_name": "Demo", "last_name": "Ota-ona", "phone": ""})
        parent.set_password("ChangeMe123!")
        parent.save()
        student, _ = User.objects.get_or_create(username="student_demo", defaults={"role": User.Role.STUDENT, "first_name": "Ali", "last_name": "Namuna"})
        student.set_password("ChangeMe123!")
        student.save()
        group, _ = StudyGroup.objects.get_or_create(name="A1", defaults={"subject": "Ingliz tili"})
        group.teachers.add(teacher)
        profile, _ = StudentProfile.objects.get_or_create(user=student, defaults={"group": group, "parent": parent})
        if profile.group_id != group.id:
            profile.group = group
            profile.parent = parent
            profile.save()
        lesson, _ = Lesson.objects.get_or_create(group=group, title="Birinchi dars", defaults={"starts_at": timezone.now()+timedelta(days=1), "teacher": teacher})
        for title in ["Uy vazifasini bajarmadi", "Darsda faol qatnashmadi", "Darsga kech qoldi", "Mavzuni yaxshi o‘zlashtirmadi", "Darsga tayyorlanmadi", "Boshqa sabab"]:
            GradeReason.objects.get_or_create(title=title)
        self.stdout.write(self.style.SUCCESS("Demo tayyor. Loginlar: admin_demo, teacher_demo, student_demo, parent_demo. Parol: ChangeMe123!"))
        self.stdout.write(self.style.WARNING("Faqat lokal sinov uchun. Internetga chiqarishdan oldin demo akkauntlar parollarini almashtiring yoki o‘chiring."))
