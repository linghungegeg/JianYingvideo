import os
from contextlib import contextmanager
from redis import Redis
from rq import Queue, Connection
from rq.worker import SimpleWorker
from rq.timeouts import BaseDeathPenalty

class NoopDeathPenalty(BaseDeathPenalty):
    """一个不执行任何操作的死亡惩罚类，避免 Windows 信号问题"""
    def __init__(self, *args, **kwargs):
        pass
    def __enter__(self):
        pass
    def __exit__(self, *args, **kwargs):
        pass

class WindowsFriendlyWorker(SimpleWorker):
    death_penalty_class = NoopDeathPenalty

if __name__ == '__main__':
    from app import create_app
    app = create_app()
    redis_url = app.config['REDIS_URL']
    redis_conn = Redis.from_url(redis_url)

    with Connection(redis_conn):
        worker = WindowsFriendlyWorker(Queue('default'))
        worker.work()