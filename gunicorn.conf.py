"""Gunicorn config for Railway deployment."""
import os

# Bind to Railway's PORT or default 8000
bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"

# Uvicorn async worker — single worker to minimize RAM (~650MB for data).
# Async means it handles concurrent requests fine without multiple workers.
worker_class = "uvicorn.workers.UvicornWorker"
workers = int(os.environ.get("WEB_CONCURRENCY", "1"))

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
