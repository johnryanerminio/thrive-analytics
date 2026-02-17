"""Gunicorn config for Railway deployment."""
import os

# Bind to Railway's PORT or default 8000
bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"

# Uvicorn async workers — each gets its own copy of the DataFrame (~650MB)
# 2 workers: if one is busy with a heavy report, the other handles
# health checks and lighter requests. Tune via WEB_CONCURRENCY env var.
worker_class = "uvicorn.workers.UvicornWorker"
workers = int(os.environ.get("WEB_CONCURRENCY", "2"))

# Timeout: allow up to 120s for heavy brand/master reports
timeout = 120

# Graceful timeout for shutdown
graceful_timeout = 30

# Keep-alive — must exceed Railway proxy keep-alive (default 60s)
keepalive = 65

# Logging
accesslog = "-"
errorlog = "-"
loglevel = "info"
