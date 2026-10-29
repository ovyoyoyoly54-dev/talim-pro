from datetime import timedelta
import secrets
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from school.models import User, StudyGroup, StudentProfile, Lesson, GradeReason

class Command(BaseCommand):
    help = "Sinov uchun namuna guruh, akkauntlar va sabablarni yaratadi."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("seed_demo faqat DEBUG=True bo‘lgan lokal muhitda ishlaydi.")
        demo_password = secrets.token_urlsafe(24)
        admin, _ = User.objects.get_or_create(username="admin_demo", defaults={"role": User.Role.ADMIN, "first_name": "Demo", "last_name": "Administrator", "is_staff": True, "is_superuser": True})
        admin.set_password(demo_password)
        admin.save()
        teacher, _ = User.objects.get_or_create(username="teacher_demo", defaults={"role": User.Role.TEACHER, "first_name": "Demo", "last_name": "O‘qituvchi"})
        teacher.set_password(demo_password)
        teacher.save()
        parent, _ = User.objects.get_or_create(username="parent_demo", defaults={"role": User.Role.PARENT, "first_name": "Demo", "last_name": "Ota-ona", "phone": ""})
        parent.set_password(demo_password)
        parent.save()
        student, _ = User.objects.get_or_create(username="student_demo", defaults={"role": User.Role.STUDENT, "first_name": "Ali", "last_name": "Namuna"})
        student.set_password(demo_password)
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
        self.stdout.write(self.style.SUCCESS("Demo tayyor. Loginlar: admin_demo, teacher_demo, student_demo, parent_demo."))
        self.stdout.write(self.style.SUCCESS(f"Faqat shu lokal ishga tushirish uchun bir martalik parol: {demo_password}"))
        self.stdout.write(self.style.WARNING("Faqat DEBUG=True lokal muhit uchun; production muhitida bu buyruq bloklanadi."))
