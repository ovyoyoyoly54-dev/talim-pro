FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt
COPY . ./
RUN groupadd --system app && useradd --system --gid app --create-home app

# Static assets are collected at image build time. Runtime secrets are injected separately.
RUN DJANGO_STATIC_BUILD=True DJANGO_DEBUG=False DJANGO_ALLOWED_HOSTS=localhost python manage.py collectstatic --noinput

USER app
EXPOSE 8000
CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py ensure_admin && exec gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers ${WEB_CONCURRENCY:-3} --access-logfile - --error-logfile -"]
