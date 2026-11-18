import os
import secrets
import sys
from pathlib import Path
from urllib.parse import urlsplit
from dotenv import load_dotenv
import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

STATIC_BUILD = os.getenv("DJANGO_STATIC_BUILD", "False").lower() == "true"
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY")
if STATIC_BUILD and not SECRET_KEY:
    # collectstatic does not use a persistent signing key; keep this process-only.
    SECRET_KEY = secrets.token_urlsafe(64)
elif not SECRET_KEY:
    SECRET_KEY = "dev-only-change-this-secret-before-deployment"
# Xavfsiz standart: DEBUG faqat DJANGO_DEBUG=True aniq yozilganda yoqiladi.
DEBUG = os.getenv("DJANGO_DEBUG", "False").lower() == "true"
ALLOWED_HOSTS = [x.strip() for x in os.getenv("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",") if x.strip()]
PUBLIC_SITE_URL = os.getenv("PUBLIC_SITE_URL", "").strip().rstrip("/")
if PUBLIC_SITE_URL:
    public_site = urlsplit(PUBLIC_SITE_URL)
    if public_site.scheme != "https" or not public_site.hostname or public_site.path or public_site.query or public_site.fragment or public_site.username:
        from django.core.exceptions import ImproperlyConfigured
        raise ImproperlyConfigured("PUBLIC_SITE_URL faqat domenning HTTPS root manzili bo‘lishi kerak.")
if not DEBUG and not STATIC_BUILD and (not os.getenv("DJANGO_SECRET_KEY") or SECRET_KEY in {
    "dev-only-change-this-secret-before-deployment",
    "replace-with-a-long-random-secret",
    "build-collectstatic-only-placeholder",
    "collectstatic-build-key-only",
    "generate-before-use",
    "change-this-to-a-long-random-secret-before-production",
}):
    from django.core.exceptions import ImproperlyConfigured
    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY sozlanishi shart (DEBUG o‘chiq). Lokal ishlab chiqish uchun .env ichiga "
        "DJANGO_DEBUG=True va random DJANGO_SECRET_KEY yozing."
    )
if not DEBUG and not os.getenv("DJANGO_ALLOWED_HOSTS", "").strip():
    from django.core.exceptions import ImproperlyConfigured
    raise ImproperlyConfigured("Production muhitida DJANGO_ALLOWED_HOSTS aniq ko‘rsatilishi shart.")

INSTALLED_APPS = [
    "django.contrib.admin", "django.contrib.auth", "django.contrib.contenttypes",
    "django.contrib.sessions", "django.contrib.messages", "django.contrib.staticfiles",
    "school.apps.SchoolConfig",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "school.security.SecurityHeadersMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "school.twofactor.AuditMiddleware",
    "school.twofactor.TwoFactorMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
if not DEBUG:
    MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")
ROOT_URLCONF = "config.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.template.context_processors.i18n",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
        "school.context_processors.platform_settings",
    "school.context_processors.csp_nonce",
    ]},
}]
WSGI_APPLICATION = "config.wsgi.application"
DATABASE_URL = os.getenv("DATABASE_URL", "")
if DATABASE_URL:
    DATABASE_SSL_REQUIRE = os.getenv("DATABASE_SSL_REQUIRE", str(not DEBUG)).lower() == "true"
    DATABASES = {"default": dj_database_url.parse(DATABASE_URL, conn_max_age=600, ssl_require=DATABASE_SSL_REQUIRE)}
else:
    # Convenient local fallback; PostgreSQL is recommended for shared/production use.
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}

AUTH_USER_MODEL = "school.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LANGUAGE_CODE = "uz"
LANGUAGES = [("uz", "O‘zbekcha"), ("ru", "Русский")]
LANGUAGE_COOKIE_AGE = 60 * 60 * 24 * 365
TIME_ZONE = "Asia/Tashkent"
USE_I18N = True
# Django'ning "uz" tarjimasi to'liq emas; loyiha tarjimalari ustidan yoziladi.
LOCALE_PATHS = [BASE_DIR / "locale"]
USE_TZ = True
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
# Yuklangan fayllar (uyga vazifa). Ular ochiq URL orqali berilmaydi: faqat ruxsat tekshiruvi
# bor view orqali yuboriladi. Productionda MEDIA_ROOT doimiy diskka (volume) ulanishi kerak.
MEDIA_ROOT = Path(os.getenv("MEDIA_ROOT", BASE_DIR / "media"))
DATA_UPLOAD_MAX_MEMORY_SIZE = 12 * 1024 * 1024
STORAGES = {"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"}}
if DEBUG:
    STORAGES["staticfiles"] = {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}
else:
    STORAGES["staticfiles"] = {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
AUTHENTICATION_BACKENDS = ["django.contrib.auth.backends.ModelBackend"]
AUTH_RATE_LIMIT_ATTEMPTS = int(os.getenv("AUTH_RATE_LIMIT_ATTEMPTS", "10"))
AUTH_RATE_LIMIT_WINDOW = int(os.getenv("AUTH_RATE_LIMIT_WINDOW", "900"))
# Proksi (Nginx, Render va h.k.) orqasida mijoz IP manzilini X-Forwarded-For dan
# olish uchun ishonchli proksilar soni. 0 bo'lsa faqat REMOTE_ADDR ishlatiladi.
TRUSTED_PROXY_COUNT = int(os.getenv("TRUSTED_PROXY_COUNT", "0"))
# Ko'pi bilan nechta o'quv guruhi yaratish mumkin (0 — cheklovsiz).
MAX_STUDY_GROUPS = int(os.getenv("MAX_STUDY_GROUPS", "5"))
# Urinishlar hisoblagichi uchun kesh. Bir nechta gunicorn ishchisi orasida umumiy
# bo'lishi uchun standart holatda ma'lumotlar bazasi keshi ishlatiladi
# (jadval `manage.py createcachetable` bilan yaratiladi).
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "django_cache",
    } if os.getenv("DJANGO_DB_CACHE", "False").lower() == "true" else {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}
if not DEBUG:
    CSRF_TRUSTED_ORIGINS = [x.strip() for x in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if x.strip()]
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = os.getenv("DJANGO_SECURE_SSL_REDIRECT", "True").lower() == "true"
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = os.getenv("DJANGO_HSTS_INCLUDE_SUBDOMAINS", "False").lower() == "true"
    SECURE_HSTS_PRELOAD = os.getenv("DJANGO_HSTS_PRELOAD", "False").lower() == "true"
    SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
    SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"


# ── To'lov tizimlari (kalitlar faqat muhit o'zgaruvchilaridan olinadi) ──
CLICK_SERVICE_ID = os.getenv("CLICK_SERVICE_ID", "").strip()
CLICK_MERCHANT_ID = os.getenv("CLICK_MERCHANT_ID", "").strip()
CLICK_SECRET_KEY = os.getenv("CLICK_SECRET_KEY", "").strip()
PAYME_MERCHANT_ID = os.getenv("PAYME_MERCHANT_ID", "").strip()
PAYME_KEY = os.getenv("PAYME_KEY", "").strip()
PAYME_TEST = os.getenv("PAYME_TEST", "False").lower() == "true"
# Oylik hisobning to'lov muddati (oyning nechanchi kuni, 1–28).
INVOICE_DUE_DAY = int(os.getenv("INVOICE_DUE_DAY", "10"))

# ── Web Push (VAPID). Kalitlar: `manage.py generate_vapid_keys` ──
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "").strip()
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "").strip()
VAPID_CLAIM_EMAIL = os.getenv("VAPID_CLAIM_EMAIL", "admin@example.com").strip()
# Push endpoint server tomonidan chaqiriladi, shuning uchun faqat ishonchli push xizmatlari
# (SSRF himoyasi). Qo'shimcha domenlar: PUSH_EXTRA_HOSTS=push.example.com,...
PUSH_ALLOWED_HOSTS = [
    "fcm.googleapis.com", "android.googleapis.com", "push.services.mozilla.com",
    "notify.windows.com", "push.apple.com",
] + [x.strip().lower() for x in os.getenv("PUSH_EXTRA_HOSTS", "").split(",") if x.strip()]

# ── Administratorlar uchun 2FA (TOTP). Testlarda o'chiriladi, productionda yoqilgan ──
ADMIN_2FA_REQUIRED = os.getenv("ADMIN_2FA_REQUIRED", "False" if "test" in sys.argv else "True").lower() == "true"
