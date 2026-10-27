"""Gunicorn settings (used by the Docker image and the systemd unit).

Run:  gunicorn -c ancient_antiquity/gunicorn.conf.py ancient_antiquity.wsgi
Every value can be overridden with an environment variable.
"""
import multiprocessing
import os

bind = os.getenv("GUNICORN_BIND", "0.0.0.0:8000")

# (2 x CPU) + 1 is the usual rule; capped so a big VM doesn't exhaust Postgres connections.
workers = int(os.getenv("GUNICORN_WORKERS", min(multiprocessing.cpu_count() * 2 + 1, 9)))
threads = int(os.getenv("GUNICORN_THREADS", "2"))
worker_class = "gthread"

# Payment gateway / SMTP calls can be slow; nginx proxy_read_timeout is set a bit higher (75s).
timeout = int(os.getenv("GUNICORN_TIMEOUT", "60"))
graceful_timeout = 30
keepalive = 5

# Recycle workers now and then to keep memory flat.
max_requests = int(os.getenv("GUNICORN_MAX_REQUESTS", "1000"))
max_requests_jitter = 100

# Logs to stdout/stderr (Docker / journald collect them).
accesslog = "-"
errorlog = "-"
loglevel = os.getenv("GUNICORN_LOG_LEVEL", "info")
access_log_format = '%({x-forwarded-for}i)s %(m)s %(U)s %(s)s %(b)s %(L)ss "%(a)s"'

# nginx is the only client; trust its X-Forwarded-* headers.
forwarded_allow_ips = os.getenv("FORWARDED_ALLOW_IPS", "*")
