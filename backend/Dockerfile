# Ancient Antiquity API (Django + gunicorn)
# Build:  docker build -t ancient-antiquity-api ./backend
# Normally built and started by ../docker-compose.yml.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MEDIA_ROOT=/app/media \
    CACHE_DIR=/tmp/ancient_antiquity_cache

WORKDIR /app

# psycopg[binary] and Pillow ship wheels, so no compiler is needed.
COPY requirements.txt .
RUN pip install -r requirements.txt

# Unprivileged user that owns only the writable folders.
RUN groupadd --system app && useradd --system --gid app --home /app --shell /usr/sbin/nologin app

COPY --chown=app:app . .

# collectstatic needs *a* production-looking configuration at build time; nothing here is used at runtime.
RUN DEBUG=False \
    SECRET_KEY=build-only-collectstatic-key-not-used-at-runtime-0000000000 \
    DATABASE_URL=sqlite:////tmp/build.sqlite3 \
    python manage.py collectstatic --noinput \
    && mkdir -p /app/media /app/exports \
    && chown -R app:app /app/media /app/exports /app/staticfiles

USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import socket; socket.create_connection(('127.0.0.1', 8000), 3)" || exit 1

# Apply database migrations, then start gunicorn (exec so it receives stop signals).
# Set RUN_MIGRATIONS=0 when running several API containers and migrate once by hand instead.
CMD ["sh", "-c", "if [ \"${RUN_MIGRATIONS:-1}\" = \"1\" ]; then python manage.py migrate --noinput; fi && exec gunicorn -c ancient_antiquity/gunicorn.conf.py ancient_antiquity.wsgi"]
