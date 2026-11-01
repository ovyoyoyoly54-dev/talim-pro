from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [("school", "0006_uzbek_verbose_names")]
    operations = [
        migrations.AddField(
            model_name="studentprofile",
            name="parent_phone",
            field=models.CharField(blank=True, max_length=24, verbose_name="ota-onaning SMS raqami"),
        ),
    ]
