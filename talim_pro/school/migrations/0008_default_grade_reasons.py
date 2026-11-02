from django.db import migrations


DEFAULT_REASONS = [
    "Uy vazifasi bajarilmagan",
    "Darsga tayyor emas",
    "Mavzuni yetarli o‘zlashtirmagan",
    "Darsda faol qatnashmagan",
    "Mustaqil ish bajarilmagan",
    "Darsga kechikkan",
]


def create_default_reasons(apps, schema_editor):
    GradeReason = apps.get_model("school", "GradeReason")
    for title in DEFAULT_REASONS:
        GradeReason.objects.get_or_create(title=title, defaults={"active": True})


class Migration(migrations.Migration):
    dependencies = [
        ("school", "0007_studentprofile_parent_phone"),
    ]

    operations = [
        migrations.RunPython(create_default_reasons, migrations.RunPython.noop),
    ]
