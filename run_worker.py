from redis import Redis
from redis.exceptions import RedisError
from rq import Connection, Queue
from rq.timeouts import BaseDeathPenalty
from rq.worker import SimpleWorker


class NoopDeathPenalty(BaseDeathPenalty):
    """No-op death penalty to avoid signal issues on Windows."""

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        pass

    def __exit__(self, *args, **kwargs):
        pass


class WindowsFriendlyWorker(SimpleWorker):
    death_penalty_class = NoopDeathPenalty


if __name__ == "__main__":
    from app import create_app

    app = create_app()
    redis_url = app.config["REDIS_URL"]
    try:
        redis_conn = Redis.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2)
        redis_conn.ping()
    except RedisError as exc:
        print(f"run_worker skipped: Redis unavailable at {redis_url}: {exc}")
        print("Current /admin and /user primary flows use in-process background tasks.")
        print("Only start Redis + run_worker.py when using legacy RQ queue paths such as MCP batch enqueue.")
        raise SystemExit(0)

    with Connection(redis_conn):
        worker = WindowsFriendlyWorker(Queue("default"))
        worker.work()
