from redis import Redis
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
    redis_conn = Redis.from_url(redis_url)

    with Connection(redis_conn):
        worker = WindowsFriendlyWorker(Queue("default"))
        worker.work()
