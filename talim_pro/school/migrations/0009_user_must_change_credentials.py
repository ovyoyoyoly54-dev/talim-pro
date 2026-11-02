from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("school", "0008_default_grade_reasons"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="must_change_credentials",
            field=models.BooleanField(default=False, verbose_name="login va parolni almashtirishi kerak"),
        ),
    ]
