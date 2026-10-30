# TA'LIM PRO — o‘quv markazi boshqaruv platformasi

Django asosidagi boshlang‘ich full-stack loyiha: o‘zbekcha interfeys, responsive dizayn, rollar, guruhlar, darslar, baholar, sabablar, davomat, reyting, jadval va sozlanadigan SMS adapteri.

## Muhim eslatma

Bu dastlabki ishlaydigan asos. Real markazda ishga tushirishdan oldin SMS-provayderingiz API formatini `school/sms.py` ichida moslang, HTTPS va zaxira nusxalarini sozlang hamda ruxsatlarni o‘zingizning jarayoningiz bo‘yicha tekshiring. Demo akkauntlar faqat lokal `DEBUG=True` rejimda, har ishga tushganda yangi random parol bilan yaratiladi. SMS sozlanmagan bo‘lsa, tizim SMS yuborilgan deb ko‘rsatmaydi — holat jurnalga yoziladi.

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
Lokal ishga tushirish uchun `.env` ichida `DJANGO_DEBUG=True`, `DJANGO_SECURE_SSL_REDIRECT=False`, random `DJANGO_SECRET_KEY` va bo‘sh `DATABASE_URL` qo‘ying. `DJANGO_SECRET_KEY` yaratish: `python -c "import secrets; print(secrets.token_urlsafe(64))"`. PostgreSQL ishlatmoqchi bo‘lsangiz, `DATABASE_URL` ni o‘zingiz yaratgan baza va parolga moslang.

### 5. PostgreSQL (ixtiyoriy Docker usuli)
Docker Desktop ishga tushgach:
```powershell
docker compose up -d db
```
`.env` dagi `POSTGRES_PASSWORD` ni kuchli tasodifiy qiymat bilan to‘ldiring; `docker-compose.yml` web xizmatida `DATABASE_URL` ni avtomatik ravishda ichki `db` xizmatiga yo‘naltiradi.
`docker compose up -d db` dan keyin Django’ni host’dan `runserver` bilan ishga tushirsangiz, `.env` dagi `DATABASE_URL` ni `postgresql://talimpro:<sizning-parolingiz>@localhost:5432/talimpro` ko‘rinishida qo‘lda kiriting. To‘liq `docker compose up` ishlatilganda `DATABASE_URL` ni bo‘sh qoldiring, Compose web container’ni ichki `db` manziliga ulaydi. `POSTGRES_PASSWORD` va URL ichidagi parol bir xil bo‘lishi kerak.

### 6. Bazani tayyorlash va sinov ma'lumotlari
```powershell
python manage.py migrate
python manage.py seed_demo
python manage.py test
python manage.py runserver
```
Lokal `.env` uchun `DJANGO_DEBUG=True` va xavfsiz random `DJANGO_SECRET_KEY` ishlating. `seed_demo` har ishga tushirilganda tasodifiy parol yaratadi va uni faqat terminalda ko‘rsatadi. Docker production entrypoint bu buyruqni chaqirmaydi.
Brauzerda `http://127.0.0.1:8000/` manzilini oching.

Demo loginlar: `admin_demo`, `teacher_demo`, `student_demo`, `parent_demo`. Buyruq yaratgan tasodifiy parol terminalda bir marta ko‘rsatiladi. U lokal sinov uchun; `DEBUG=False` bo‘lganda `seed_demo` xatolik bilan to‘xtaydi. Production administratorini `createsuperuser` orqali yarating.

## Asosiy funksiyalar
- To‘rtta rol va autentifikatsiya
- O‘qituvchi faqat o‘ziga biriktirilgan dars/guruhlar bilan ishlaydi
- Maksimal 5 ta guruh (model darajasidagi tekshiruv)
- 0–10 baho, 8 dan past baho uchun kamida bitta sabab
- Bir nechta sabab, izoh va davomat
- O‘rtacha/jami ball reytingi
- Dars jadvali
- Ota-onaga SMS adapteri va SMS yuborish jurnali
- Telefon OTP orqali parol tiklash va akkauntni yopish

## SMS integratsiyasi
`.env` da quyidagilarni to‘ldiring:
```env
SMS_API_URL=https://sms-provider.example/api/send
SMS_API_TOKEN=provider-token
SMS_SENDER=TalimPro
```
Bu umumiy JSON adapteri (`to`, `message`, `sender`) va Bearer token ishlatadi. SMS provayderingizning hujjatiga qarab `school/sms.py` dagi request qismini moslang. Haqiqiy provayderdan test raqamiga sinov yubormasdan turib, SMS ishlashini tasdiqlamang.

Parol tiklash va akkauntni yopish ham shu `SMS_API_URL`, `SMS_API_TOKEN`, `SMS_SENDER` sozlamalaridan foydalanadi. SMS adapteri `to`, `message`, `sender` maydonlarini yuboradi; provayderning haqiqiy API formatiga moslab tekshirilmaguncha OTP SMS ishlaydi deb bo‘lmaydi. OTP 10 daqiqa amal qiladi, 5 ta noto‘g‘ri urinishdan keyin bekor bo‘ladi; kod SMS jurnalida saqlanmaydi.

### Render’da administrator va tizimga kirish

Foydalanuvchilar dashboard’i `/dashboard/`, kirish sahifasi `/login/`. Dastlabki administratorni Render Dashboard → Web Service → **Shell** orqali `python manage.py createsuperuser` buyrug‘i bilan interaktiv yarating. O‘ziga xos login va kuchli parol tanlang; parolni environment variable, kod yoki GitHub’da saqlamang. Buyruq tugagach, `/login/` sahifasida shu hisob bilan kiring. Butun ilova uchun umumiy administrator paroli yoki yashirin backdoor bo‘lmasligi kerak.

Render’dagi ma’lumotlar bazasi PostgreSQL bo‘lsin: shu hududdagi Render PostgreSQL bazasining internal URL manzilini `DATABASE_URL` qilib Environment bo‘limiga kiriting. `DJANGO_DEBUG=False`, `DJANGO_ALLOWED_HOSTS` va `DJANGO_CSRF_TRUSTED_ORIGINS` qiymatlarini service’ning haqiqiy `onrender.com` manzili yoki bog‘langan domeniga moslang; `PUBLIC_SITE_URL` uchun HTTPS public root manzilini kiriting. Barcha maxfiy qiymatlarni Render Environment’da saqlang.

Agar sayt yuklanishidan oldin brauzerning o‘z popup oynasi chiqsa, bu Django’ning `/login/` sahifasi emas. Render service public **Web Service** ekanini va Render tomondagi himoya sozlamalarini tekshiring; Django kodi service tashqarisidagi HTTP Basic Auth’ni olib tashlay olmaydi.

## Ishlab chiqarish muhiti

Production muhitida demo ma'lumotlarini yaratmaymiz. Docker entrypoint faqat migratsiyalarni qo‘llaydi; `seed_demo` esa `DEBUG=False` bo‘lganda ishlashdan bosh tortadi.

### Saytni serverga chiqarish

Loyiha Docker orqali Django + PostgreSQL sifatida ishga tushadi. `.env.example` ni `.env` ga ko‘chiring va quyidagi qiymatlarni haqiqiy hosting/domain ma'lumotlari bilan to‘ldiring. Domen yoki hosting hali tanlanmagan bo‘lsa, misol domen qo‘ymang; deploy bosqichini kuting.

```env
DJANGO_SECRET_KEY=<kamida 50 belgili random maxfiy qiymat>
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=<haqiqiy-domen>,<www-domen-bo‘lsa>
DJANGO_CSRF_TRUSTED_ORIGINS=https://<haqiqiy-domen>,https://<www-domen-bo‘lsa>
PUBLIC_SITE_URL=https://<haqiqiy-domen>
DJANGO_SECURE_SSL_REDIRECT=True
POSTGRES_PASSWORD=<kuchli-va-url-uchun-xavfsiz-parol>
DATABASE_SSL_REQUIRE=False
SMS_API_URL=
SMS_API_TOKEN=
SMS_SENDER=
```

`DJANGO_SECRET_KEY` hosil qilish. Quyidagi placeholder qiymatlarni aynan ko‘chirmang; burchak qavs ichidagi qismlarni domen/hosting bergan haqiqiy qiymatlar bilan almashtiring. Domen host qiymatida port yoki protokol yozmang.

```powershell
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

`DATABASE_SSL_REQUIRE=False` Docker Compose ichidagi PostgreSQL uchun. Tashqi boshqariladigan PostgreSQL ishlatilsa, `DATABASE_URL` ni provayder bergan manzilga o‘rnating va provayder TLS talab qilsa `DATABASE_SSL_REQUIRE=True` qo‘ying.

Ixtiyoriy qiymatlar: `SMS_API_URL`, `SMS_API_TOKEN`, `SMS_SENDER`; hosting portni o‘zi bersa `PORT`, worker sonini sozlash uchun `WEB_CONCURRENCY`.

Deploy bosqichlari:

1. Domenni hostingga yo‘naltiring va TLS sertifikat / reverse proxy sozlang. Proxy `X-Forwarded-Proto: https` yuborsin.
2. `.env` faylini hosting serverida yarating. U `.gitignore` va `.dockerignore` bilan Git hamda image build kontekstidan chiqarilgan.
3. Loyihani serverga olib chiqing va quyidagini bajaring:

```powershell
docker compose up --build -d
```

4. Birinchi administratorni `docker compose exec web python manage.py createsuperuser` bilan yarating. Migratsiyalar app ishga tushganda avtomatik bajariladi; production muhitida `makemigrations` ishlatmang.
5. Hosting firewall’da faqat zarur web portlarni oching. PostgreSQL porti Compose’da `127.0.0.1` ga bog‘langan, ma'lumotlar volume’da qoladi; muntazam zaxira nusxa oling.
6. Sayt ishlagach, `/robots.txt` va `/sitemap.xml` ni brauzerda tekshiring.

### Google Search Console

1. Google Search Console’da domen property (DNS TXT orqali) yoki URL-prefix property yarating.
2. Google bergan TXT/meta/HTML tekshiruv qiymatini o‘zingizning domeningizga joylashtirib tasdiqlang; tekshiruv qiymatini GitHub’ga qo‘ymang.
3. Property tasdiqlangach, `https://<haqiqiy-domen>/sitemap.xml` manzilini Sitemaps bo‘limida yuboring.
4. URL Inspection bilan faqat bosh sahifa indeksga yaroqliligini tekshiring. Sitemap’da faqat ommaviy bosh sahifa bor; login, dashboard, baholar, reyting, jadval va profillar robots hamda `noindex` bilan cheklanadi.

Google saytingizni albatta crawl yoki indeks qilishini kafolatlamaydi; natija uning tekshiruv va indeks siyosatiga bog‘liq.

### PWA va APK

Ommaviy bosh sahifa title, description, canonical va Open Graph metama'lumotlariga ega. `robots.txt` faqat bosh sahifani sitemap’ga kiritadi; indexlash uchun haqiqiy domenli HTTPS URL kerak.

Sayt telefon ekraniga moslashadi va qo‘llab-quvvatlanadigan brauzerlarda o‘rnatiladigan PWA sifatida ishlaydi. Internet bo‘lmaganda faqat offline ma'lumot sahifasi ko‘rsatiladi; baho, davomat va boshqa kirilgan sahifalar keshga yozilmaydi.

Android Studio loyihasi `android/` papkasida. Hozircha `siteUrl=https://example.com` namuna qiymati; APK yig‘ishdan oldin uni hostingga chiqqan haqiqiy HTTPS domen bilan almashtiring. Hosting va domen tayyor bo‘lmaguncha APK ishlaydi deb bo‘lmaydi. Repository’da Gradle Wrapper (`gradlew`) yo‘q; Android Studio’da Gradle 8.13 va JDK 17 bilan sync/build qiling yoki loyiha uchun wrapper yarating. Android SDK Platform 36 kerak. **Build → Build Bundle(s) / APK(s) → Build APK(s)** ni tanlang. APK hosted Django saytiga ulanadi, lokal serverni ichiga olmaydi.
