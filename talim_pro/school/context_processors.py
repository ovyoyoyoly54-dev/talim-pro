from .models import Notification, PlatformSettings, StudentProfile, StudyGroup, User

# Sidebar bo'limlari: qaysi sahifa qaysi bo'limga tegishli (shu bo'lim ochiq turadi).
NAV_SECTIONS = {
    "main": {"dashboard", "schedule"},
    "rooms": {"group_management", "group_detail", "room_detail", "add_student_to_group", "teacher_assign_group"},
    "learning": {"grade_lesson", "lesson_journal", "homework_list", "homework_create", "homework_detail", "ranking", "student_detail"},
    "manage": {"teacher_management", "lesson_create", "lesson_reschedule", "applications_list"},
    "finance": {"payments_overview", "generate_invoices", "debtors_list", "remind_debtors", "reports_home", "attendance_report", "ranking_report"},
    "account": {"notification_list", "settings_panel", "two_factor_setup", "first_login_credentials"},
}


def _nav_rooms(user):
    if user.is_superuser or user.role == User.Role.ADMIN:
        return list(StudyGroup.objects.only("id", "name").order_by("name"))
    if user.role == User.Role.TEACHER:
        return list(StudyGroup.objects.filter(teachers=user).only("id", "name").order_by("name"))
    if user.role == User.Role.STUDENT:
        return list(StudyGroup.objects.filter(students__user=user).only("id", "name").distinct())
    if user.role == User.Role.PARENT:
        return list(StudyGroup.objects.filter(students__parent=user).only("id", "name").distinct().order_by("name"))
    return []


def platform_settings(request):
    unread = 0
    rooms, open_section = [], ""
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        unread = Notification.objects.filter(user=user, read_at__isnull=True).count()
        rooms = _nav_rooms(user)
        match = getattr(request, "resolver_match", None)
        name = match.url_name if match else ""
        open_section = next((key for key, names in NAV_SECTIONS.items() if name in names), "")
    return {
        "platform_settings": PlatformSettings.objects.filter(pk=1).first(),
        "unread_notifications": unread,
        "nav_rooms": rooms,
        "nav_open": open_section,
    }


def csp_nonce(request):
    """Inline <script> teglariga `nonce="{{ csp_nonce }}"` qo'yish uchun."""
    return {"csp_nonce": getattr(request, "csp_nonce", "")}
