"""Minimal .po -> .mo kompilyatori (gettext `msgfmt` o'rnini bosadi).

Django `compilemessages` buyrug'i tizimda `msgfmt` dasturi bo'lishini talab
qiladi. Windows yoki minimal serverda u ko'pincha o'rnatilmagan bo'ladi,
shuning uchun loyiha tarjimalarini yig'ish uchun bu kichik skript yetarli.

Ishlatish:
    python tools/po2mo.py locale/uz/LC_MESSAGES/django.po

Natija: shu papkadagi `django.mo` fayli (Django aynan shuni o'qiydi).
"""
from __future__ import annotations

import ast
import struct
import sys
from pathlib import Path

MAGIC = 0x950412DE
VERSION = 0


def parse_po(path: Path) -> dict[str, str]:
    """Har bir yozuv uchun {"msgid\\0msgid_plural": "msgstr"} lug'atini qaytaradi."""
    entries: dict[str, str] = {}
    msgid: str | None = None
    plural: str | None = None
    msgstr: str | None = None
    mode = "id"
    pending_field: str | None = None

    def flush() -> None:
        nonlocal msgid, plural, msgstr, mode
        if msgid is not None and msgstr is not None:
            key = msgid if plural is None else f"{msgid}\0{plural}"
            entries[key] = msgstr
        msgid = None
        plural = None
        msgstr = None
        mode = "id"

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("msgctxt "):
            # msgctxt ishlatilmaydi, lekin uchrasa o'tkazib yuboramiz.
            continue
        if line.startswith("msgid_plural "):
            plural = ast.literal_eval(line[len("msgid_plural "):])
            mode = "plural"
            continue
        if line.startswith("msgid "):
            flush()
            msgid = ast.literal_eval(line[len("msgid "):])
            msgstr = ""
            mode = "id"
            pending_field = "msgid"
            continue
        if line.startswith("msgstr[0] "):
            msgstr = ast.literal_eval(line[len("msgstr[0] "):])
            mode = "str"
            pending_field = "msgstr"
            continue
        if line.startswith("msgstr["):
            # nplurals=1 bo'lgani uchun faqat [0] kerak; qolganini tashlaymiz.
            mode = "skip"
            pending_field = None
            continue
        if line.startswith("msgstr "):
            msgstr = ast.literal_eval(line[len("msgstr "):])
            mode = "str"
            pending_field = "msgstr"
            continue
        if line.startswith('"'):
            # Davomiy satr.
            part = ast.literal_eval(line)
            if pending_field == "msgid":
                msgid = (msgid or "") + part
            elif pending_field == "msgstr" and msgstr is not None:
                msgstr += part
            continue
    flush()
    return entries


def build_mo(entries: dict[str, str]) -> bytes:
    keys = sorted(entries)
    header_size = 7 * 4
    table_size = len(keys) * 8
    ids_offset = header_size + table_size * 2

    # 1-bosqich: msgid jadvalini yig'amiz.
    ids = b""
    ids_table_entries: list[tuple[int, int]] = []
    for key in keys:
        key_bytes = key.encode("utf-8")
        ids_table_entries.append((len(key_bytes), ids_offset + len(ids)))
        ids += key_bytes + b"\0"

    # 2-bosqich: msgstr jadvali msgid jadvalidan keyin boshlanadi.
    strs_offset = ids_offset + len(ids)
    strs = b""
    strs_table_entries: list[tuple[int, int]] = []
    for key in keys:
        val_bytes = entries[key].encode("utf-8")
        strs_table_entries.append((len(val_bytes), strs_offset + len(strs)))
        strs += val_bytes + b"\0"

    ids_table = b"".join(struct.pack("2i", length, offset) for length, offset in ids_table_entries)
    strs_table = b"".join(struct.pack("2i", length, offset) for length, offset in strs_table_entries)

    header = struct.pack(
        "7I",
        MAGIC,
        VERSION,
        len(keys),
        7 * 4,                                   # msgid jadvali boshlanishi
        7 * 4 + len(keys) * 8,                   # msgstr jadvali boshlanishi
        0,                                       # hash jadvali hajmi
        0,                                       # hash jadvali boshlanishi
    )
    return header + ids_table + strs_table + ids + strs


def main(argv: list[str]) -> int:
    if len(argv) not in (2, 3):
        print(__doc__)
        return 2
    po_path = Path(argv[1])
    mo_path = Path(argv[2]) if len(argv) == 3 else po_path.with_suffix(".mo")
    entries = parse_po(po_path)
    mo_path.write_bytes(build_mo(entries))
    print(f"{po_path} -> {mo_path} ({len(entries)} yozuv)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
