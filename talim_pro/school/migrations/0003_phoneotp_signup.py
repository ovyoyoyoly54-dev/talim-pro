from django.db import migrations
from django.db import models


class Migration(migrations.Migration):
    dependencies = [("school", "0002_phoneotp")]

    operations = [
        migrations.AlterField(
            model_name="phoneotp",
            name="purpose",
            field=models.CharField(
                choices=[("signup", "Yangi akkaunt"), ("reset_password", "Parolni tiklash"), ("close_account", "Akkauntni yopish")],
                max_length=20,
            ),
        ),
    ]
