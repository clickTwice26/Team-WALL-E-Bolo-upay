"""gunicorn settings for the API (deploy/Dockerfile: `gunicorn -c gunicorn.conf.py app.main:app`).

WEB_CONCURRENCY workers, default one per CPU. Each worker is its own process
and loads the risk model once at startup. All workers share the SQLite file
(WAL mode), which also holds the PIN guard, biometric challenges and
idempotency keys, so no Redis is needed at this scale (docs/SCALE.md).
"""
import multiprocessing
import os
import secrets
import shutil
import sys
import tempfile

bind = os.getenv("BIND", "0.0.0.0:8000")
worker_class = "uvicorn_worker.UvicornWorker"
workers = int(os.getenv("WEB_CONCURRENCY") or multiprocessing.cpu_count())
forwarded_allow_ips = os.getenv("FORWARDED_ALLOW_IPS", "*")  # behind Caddy, like uvicorn --proxy-headers
timeout = 60
keepalive = 5

# one signing key for every worker: without AUTH_SECRET each worker would pick
# its own random key and reject tokens issued by the others
if not os.getenv("AUTH_SECRET"):
    print("AUTH_SECRET is not set: using a random key, so sessions end when the server restarts",
          file=sys.stderr)
    os.environ["AUTH_SECRET"] = secrets.token_hex(32)

# the model's predict uses OpenMP threads, by default one per CPU: with one
# worker per CPU that is CPUs² threads fighting for the cores (assess p95 went
# from ~0.1 s to over 2 s at 50 users). One thread per worker; the workers
# are the parallelism.
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

# Prometheus: each worker writes its counters to this folder, /metrics adds them up
os.environ.setdefault("PROMETHEUS_MULTIPROC_DIR", os.path.join(tempfile.gettempdir(), "bolo-prometheus"))


def on_starting(server):
    d = os.environ["PROMETHEUS_MULTIPROC_DIR"]
    shutil.rmtree(d, ignore_errors=True)  # counters from an earlier run would be added in
    os.makedirs(d)


def child_exit(server, worker):
    from prometheus_client import multiprocess
    multiprocess.mark_process_dead(worker.pid)
