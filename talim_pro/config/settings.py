import os
from pathlib import Path
from urllib.parse import urlsplit
from dotenv import load_dotenv
import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-only-change-this-secret-before-deployment")
DEBUG = os.getenv("DJANGO_DEBUG", "True").lower() == "true"
ALLOWED_HOSTS = [x.strip() for x in os.getenv("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",") if x.strip()]
PUBLIC_SITE_URL = os.getenv("PUBLIC_SITE_URL", "").strip().rstrip("/")
if PUBLIC_SITE_URL:
    public_site = urlsplit(PUBLIC_SITE_URL)
    if public_site.scheme != "https" or not public_site.hostname or public_site.path or public_site.query or public_site.fragment or public_site.username:
        from django.core.exceptions import ImproperlyConfigured
        raise ImproperlyConfigured("PUBLIC_SITE_URL faqat domenning HTTPS root manzili bo‘lishi kerak.")
if not DEBUG and (not SECRET_KEY or SECRET_KEY in {
    "dev-only-change-this-secret-before-deployment",
    "replace-with-a-long-random-secret",
    "build-collectstatic-only-placeholder",
    "collectstatic-build-key-only",
    "generate-before-use",
}):
    from django.core.exceptions import ImproperlyConfigured
    raise ImproperlyConfigured("Production muhitida DJANGO_SECRET_KEY sozlanishi shart.")
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
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
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
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
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
TIME_ZONE = "Asia/Tashkent"
USE_I18N = True
USE_TZ = True
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
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
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
if not DEBUG:
    CSRF_TRUSTED_ORIGINS = [x.strip() for x in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if x.strip()]
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = os.getenv("DJANGO_SECURE_SSL_REDIRECT", "True").lower() == "true"
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
