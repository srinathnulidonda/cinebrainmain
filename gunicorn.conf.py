# gunicorn.conf.py

import multiprocessing
import os
import shutil

os.environ.setdefault("PROMETHEUS_MULTIPROC_DIR", "/tmp/prometheus")

from prometheus_client import multiprocess

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
workers = int(os.environ.get("WEB_CONCURRENCY", min(multiprocessing.cpu_count() * 2 + 1, 8)))
worker_class = "uvicorn_worker.UvicornWorker"
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "60"))
graceful_timeout = 30
keepalive = 5
max_requests = 2000
max_requests_jitter = 200
preload_app = False
accesslog = None
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info").lower()
forwarded_allow_ips = os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1")
worker_tmp_dir = "/dev/shm" if os.path.isdir("/dev/shm") else None


def on_starting(server):
    path = os.environ["PROMETHEUS_MULTIPROC_DIR"]
    shutil.rmtree(path, ignore_errors=True)
    os.makedirs(path, exist_ok=True)


def child_exit(server, worker):

    multiprocess.mark_process_dead(worker.pid)
