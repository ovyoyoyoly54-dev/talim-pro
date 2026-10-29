from django.apps import AppConfig
class SchoolConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "school"
    verbose_name = "Ta'lim PRO"

    def ready(self):
        from . import signals  # noqa: F401
