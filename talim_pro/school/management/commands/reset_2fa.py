from django.core.management.base import BaseCommand, CommandError

from school.models import TwoFactorDevice, User


class Command(BaseCommand):
    help = "Foydalanuvchining 2FA sozlamasini o‘chiradi (telefon va zaxira kodlar yo‘qolganda)."

    def add_arguments(self, parser):
        parser.add_argument("username")

    def handle(self, *args, username, **options):
        user = User.objects.filter(username=username).first()
        if user is None:
            raise CommandError("Foydalanuvchi topilmadi.")
        deleted, _ = TwoFactorDevice.objects.filter(user=user).delete()
        self.stdout.write(self.style.SUCCESS(
            "2FA o‘chirildi. Keyingi kirishda qayta sozlanadi." if deleted else "Bu foydalanuvchida 2FA yo‘q edi."))
