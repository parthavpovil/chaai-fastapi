"""
Gunicorn configuration for ChatSaaS Backend production deployment
"""
import multiprocessing
import os

# Server socket
bind = "0.0.0.0:8000"
backlog = 2048

# Worker processes — capped at 2 because the container is limited to
# cpus: "1.0" in docker-compose.prod.yml. More workers just contend for
# the single CPU during cold import (each worker re-imports the full
# FastAPI app, ~45s on this VPS) and inflate startup past the healthcheck
# start_period.
workers = min(multiprocessing.cpu_count() * 2 + 1, 2)
worker_class = "uvicorn.workers.UvicornWorker"
worker_connections = 1000
max_requests = 1000
max_requests_jitter = 50

# Timeout settings — webchat/RAG calls can take 60-90s
timeout = 120
keepalive = 5
graceful_timeout = 60

# Logging
accesslog = "-"
errorlog = "-"
loglevel = "info"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Process naming
proc_name = "chatsaas-backend"

# Server mechanics
daemon = False
pidfile = None
user = None
group = None
tmp_upload_dir = None

# SSL (if certificates are provided)
keyfile = os.environ.get("SSL_KEYFILE")
certfile = os.environ.get("SSL_CERTFILE")

# Worker process settings
# preload_app must stay False with UvicornWorker: forking after the event loop
# starts corrupts asyncio/asyncpg/Redis state in child processes.
preload_app = False
worker_tmp_dir = "/dev/shm"

# Security
limit_request_line = 4094
limit_request_fields = 100
limit_request_field_size = 8190

def when_ready(server):
    """Called just after the server is started."""
    server.log.info("ChatSaaS Backend server is ready. Listening on: %s", server.address)

def worker_int(worker):
    """Called just after a worker has been killed by a SIGINT signal."""
    worker.log.info("Worker received INT or QUIT signal")

def pre_fork(server, worker):
    """Called just before a worker is forked."""
    server.log.info("Worker spawned (pid: %s)", worker.pid)

def worker_abort(worker):
    """Called when a worker receives the SIGABRT signal."""
    worker.log.info("Worker received SIGABRT signal")