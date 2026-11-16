"""Davomat va reyting hisobotlari: Excel (.xlsx) va PDF eksporti."""
import io
from datetime import date, datetime

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Avg, Count, Q, Sum
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.translation import gettext as _

from .models import Attendance, StudentProfile, StudyGroup, User
from .views import is_admin

FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _accessible_groups(user):
    if is_admin(user):
        return StudyGroup.objects.all()
    if user.role == User.Role.TEACHER:
        return StudyGroup.objects.filter(teachers=user)
    raise PermissionDenied


def _parse_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _safe(value):
    """Excel formula injection'dan himoya: '=' bilan boshlanadigan matn oldiga ' qo‘yiladi."""
    if isinstance(value, str) and value.startswith(FORMULA_PREFIXES):
        return "'" + value
    return value


def attendance_rows(groups, start=None, end=None):
    lesson_filter = Q()
    if start:
        lesson_filter &= Q(attendance__lesson__starts_at__date__gte=start)
    if end:
        lesson_filter &= Q(attendance__lesson__starts_at__date__lte=end)
    students = StudentProfile.objects.filter(
        group__in=groups, user__role=User.Role.STUDENT, user__is_active=True,
    ).select_related("user", "group").annotate(
        total=Count("attendance", filter=lesson_filter, distinct=True),
        present=Count("attendance", filter=lesson_filter & Q(attendance__status=Attendance.Status.PRESENT), distinct=True),
        late=Count("attendance", filter=lesson_filter & Q(attendance__status=Attendance.Status.LATE), distinct=True),
        absent=Count("attendance", filter=lesson_filter & Q(attendance__status=Attendance.Status.ABSENT), distinct=True),
    ).order_by("group__name", "user__last_name", "user__first_name")
    rows = []
    for st in students:
        attended = st.present + st.late
        percent = round(attended * 100 / st.total, 1) if st.total else None
        rows.append([st.user.get_full_name() or st.user.username, st.group.name, st.total,
                     st.present, st.late, st.absent, percent])
    return rows


def ranking_rows(groups):
    students = StudentProfile.objects.filter(
        group__in=groups, user__role=User.Role.STUDENT, user__is_active=True,
    ).select_related("user", "group").annotate(
        average=Avg("grades__score"), total_score=Sum("grades__score"), graded=Count("grades", distinct=True),
    ).order_by("-average", "-total_score", "user__last_name")
    return [
        [place, st.user.get_full_name() or st.user.username, st.group.name, st.graded,
         st.total_score or 0, round(st.average, 2) if st.average is not None else None]
        for place, st in enumerate(students, start=1)
    ]


def _xlsx(title, headers, rows, filename):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = title[:31]
    ws.append([_safe(h) for h in headers])
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="102544")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for row in rows:
        ws.append([_safe(v) if v is not None else "" for v in row])
    for idx, header in enumerate(headers, start=1):
        width = max([len(str(header))] + [len(str(r[idx - 1])) for r in rows if r[idx - 1] is not None]) + 3
        ws.column_dimensions[get_column_letter(idx)].width = min(width, 40)
    ws.freeze_panes = "A2"
    buffer = io.BytesIO()
    wb.save(buffer)
    response = HttpResponse(buffer.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = f'attachment; filename="{filename}.xlsx"'
    return response


def _register_fonts():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    fonts = settings.BASE_DIR / "static" / "school" / "fonts"
    if "DejaVuSans" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("DejaVuSans", str(fonts / "DejaVuSans.ttf")))
        pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", str(fonts / "DejaVuSans-Bold.ttf")))


def _pdf(title, subtitle, headers, rows, filename):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    _register_fonts()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), leftMargin=24, rightMargin=24, topMargin=28, bottomMargin=28, title=title)
    h1 = ParagraphStyle("h1", fontName="DejaVuSans-Bold", fontSize=15, spaceAfter=4)
    small = ParagraphStyle("small", fontName="DejaVuSans", fontSize=9, textColor=colors.grey, spaceAfter=10)
    data = [headers] + [["" if v is None else v for v in row] for row in rows]
    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "DejaVuSans-Bold"), ("FONTNAME", (0, 1), (-1, -1), "DejaVuSans"),
        ("FONTSIZE", (0, 0), (-1, -1), 9), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#102544")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f7fb")]),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#c9d1e0")), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    # Paragraph matn XML sifatida o‘qiladi: foydalanuvchi kiritgan belgilar escape qilinadi.
    from xml.sax.saxutils import escape
    doc.build([Paragraph(escape(title), h1), Paragraph(escape(subtitle), small), Spacer(1, 4), table])
    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}.pdf"'
    return response


def _respond(fmt, title, subtitle, headers, rows, stem):
    stamp = timezone.localdate().strftime("%Y%m%d")
    filename = f"{stem}-{stamp}"
    if fmt == "xlsx":
        return _xlsx(title, headers, rows, filename)
    if fmt == "pdf":
        return _pdf(title, subtitle, headers, rows, filename)
    raise Http404


@login_required
def reports_home(request):
    groups = _accessible_groups(request.user)
    return render(request, "school/reports.html", {"groups": groups, "today": timezone.localdate()})


def _selected_groups(request):
    groups = _accessible_groups(request.user)
    group_id = request.GET.get("group")
    if group_id:
        if not group_id.isdigit():
            raise Http404
        groups = groups.filter(pk=int(group_id))
        if not groups.exists():
            raise PermissionDenied
    return groups


@login_required
def attendance_report(request):
    groups = _selected_groups(request)
    start, end = _parse_date(request.GET.get("from")), _parse_date(request.GET.get("to"))
    headers = [_("O‘quvchi"), _("Guruh"), _("Darslar"), _("Qatnashdi"), _("Kechikdi"), _("Kelmagan"), _("Davomat %")]
    period = f"{start or '…'} — {end or '…'}"
    return _respond(request.GET.get("format", "xlsx"), _("Davomat hisoboti"), f"{_('Davr')}: {period}",
                    headers, attendance_rows(groups, start, end), "davomat")


@login_required
def ranking_report(request):
    groups = _selected_groups(request)
    headers = [_("O‘rin"), _("O‘quvchi"), _("Guruh"), _("Baholangan darslar"), _("Jami ball"), _("O‘rtacha")]
    return _respond(request.GET.get("format", "xlsx"), _("Reyting hisoboti"),
                    timezone.localdate().strftime("%d.%m.%Y"), headers, ranking_rows(groups), "reyting")
