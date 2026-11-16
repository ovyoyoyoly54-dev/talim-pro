"""Shablon va Python kodidagi tarjima qilinadigan matnlarni (msgid) yig‘adi.

gettext (`xgettext`) bo‘lmagan muhitlar uchun yengil o‘rinbosar. Ishlatish:

    python tools/extract_messages.py            # msgidlar ro‘yxatini chiqaradi
    python tools/extract_messages.py --missing  # locale/ru da tarjimasi yo‘qlarini chiqaradi

Qamrov: `{% trans "..." %}`, `{% trans '...' %}` (shablonlar) va `_("...")` /
`gettext("...")` (school/*.py, test fayllaridan tashqari).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_RE = re.compile(r"""\{%\s*trans\s+(?:"((?:[^"\\]|\\.)*)"|'((?:[^'\\]|\\.)*)')""")
PY_RE = re.compile(r"""(?<![\w.])(?:_|gettext|gettext_lazy)\(\s*(?:"((?:[^"\\]|\\.)*)"|'((?:[^'\\]|\\.)*)')""")


def collect() -> list[str]:
    found: dict[str, None] = {}
    for path in sorted((ROOT / "templates").rglob("*.html")):
        for match in TEMPLATE_RE.finditer(path.read_text(encoding="utf-8")):
            found.setdefault(match.group(1) or match.group(2), None)
    for path in sorted((ROOT / "school").glob("*.py")):
        if path.name.startswith("test") or path.name == "tests.py":
            continue
        for match in PY_RE.finditer(path.read_text(encoding="utf-8")):
            found.setdefault(match.group(1) or match.group(2), None)
    return list(found)


def po_entries(path: Path) -> dict[str, str]:
    sys.path.insert(0, str(ROOT / "tools"))
    from po2mo import parse_po
    return parse_po(path)


if __name__ == "__main__":
    messages = collect()
    if "--missing" in sys.argv:
        entries = po_entries(ROOT / "locale" / "ru" / "LC_MESSAGES" / "django.po")
        messages = [m for m in messages if not entries.get(m)]
    print("\n".join(messages))
