# TA'LIM PRO — o‘quv markazi boshqaruv platformasi

Django asosidagi boshlang‘ich full-stack loyiha: o‘zbekcha interfeys, responsive dizayn, rollar, guruhlar, darslar, baholar, sabablar, davomat, reyting, jadval va sozlanadigan SMS adapteri.

## Muhim eslatma

Bu dastlabki ishlaydigan asos. Real markazda ishga tushirishdan oldin SMS-provayderingiz API formatini `school/sms.py` ichida moslang, demo akkauntlarini o‘chiring/parollarini almashtiring, HTTPS va zaxira nusxalarini sozlang hamda ruxsatlarni o‘zingizning jarayoningiz bo‘yicha tekshiring. SMS sozlanmagan bo‘lsa, tizim SMS yuborilgan deb ko‘rsatmaydi — holat jurnalga yoziladi.

## Windows 10/11 da ishga tushirish

### 1. Kerakli dasturlar
- Python 3.11 yoki 3.12
- PostgreSQL 16 (yoki Docker Desktop)
- VS Code tavsiya etiladi

### 2. Loyihani ochish
ZIP arxivni, masalan, `C:\\Projects\\talim_pro` papkasiga chiqaring va VS Code terminalida shu papkani oching.

### 3. Virtual muhit
```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```
Agar PowerShell skript ishga tushishiga ruxsat bermasa, terminalda `cmd` ochib quyidagidan foydalaning:
```bat
.venv\Scripts\activate.bat
```

### 4. Muhit sozlamalari
```powershell
Copy-Item .env.example .env
```
`.env` faylida `DJANGO_SECRET_KEY` qiymatini o‘zgartiring. PostgreSQL ishlatmoqchi bo‘lsangiz, `DATABASE_URL` ni o‘zingiz yaratgan baza va parolga moslang. Lokal tezkor sinov uchun `DATABASE_URL` ni bo‘sh qoldirsangiz, SQLite ishlatiladi.

### 5. PostgreSQL (ixtiyoriy Docker usuli)
Docker Desktop ishga tushgach:
```powershell
docker compose up -d db
```
`.env` dagi `DATABASE_URL` qiymatini quyidagiga moslang:
`postgresql://talimpro:change-this-password@localhost:5432/talimpro`
`POSTGRES_PASSWORD` va URL ichidagi parol bir xil bo‘lishi kerak. Real foydalanishda kuchli parol tanlang.

### 6. Bazani tayyorlash va sinov ma'lumotlari
```powershell
python manage.py makemigrations school
python manage.py migrate
python manage.py seed_demo
python manage.py test
python manage.py runserver
```
Brauzerda `http://127.0.0.1:8000/` manzilini oching.

### Demo loginlar (faqat lokal sinov uchun)
| Rol | Login |
|---|---|
| Administrator | `admin_demo` |
| O‘qituvchi | `teacher_demo` |
| O‘quvchi | `student_demo` |
| Ota-ona | `parent_demo` |

Demo parol: `ChangeMe123!`

Internetga joylashtirishdan oldin demo akkauntlarni o‘chiring yoki kuchli, alohida parollarga almashtiring. Administrator uchun `python manage.py createsuperuser` orqali ham superuser yaratish mumkin.

## Asosiy funksiyalar
- To‘rtta rol va autentifikatsiya
- O‘qituvchi faqat o‘ziga biriktirilgan dars/guruhlar bilan ishlaydi
- Maksimal 5 ta guruh (model darajasidagi tekshiruv)
- 0–10 baho, 8 dan past baho uchun kamida bitta sabab
- Bir nechta sabab, izoh va davomat
- O‘rtacha/jami ball reytingi
- Dars jadvali
- Ota-onaga SMS adapteri va SMS yuborish jurnali

## SMS integratsiyasi
`.env` da quyidagilarni to‘ldiring:
```env
SMS_API_URL=https://sms-provider.example/api/send
SMS_API_TOKEN=provider-token
SMS_SENDER=TalimPro
```
Bu umumiy JSON adapteri (`to`, `message`, `sender`) va Bearer token ishlatadi. SMS provayderingizning hujjatiga qarab `school/sms.py` dagi request qismini moslang. Haqiqiy provayderdan test raqamiga sinov yubormasdan turib, SMS ishlashini tasdiqlamang.

## Ishlab chiqarish muhiti
- `DJANGO_DEBUG=False`
- `DJANGO_SECRET_KEY` uchun uzun tasodifiy maxfiy qiymat
- `DJANGO_ALLOWED_HOSTS` ga domen
- HTTPS, xavfsiz DB paroli, zaxira nusxa, log monitoring
- Demo loginlarni o‘chirish
- SMS provayderning haqiqiy API formatini tekshirish
- Baholash va ota-onaga xabar yuborish siyosatini markaz bilan kelishish
