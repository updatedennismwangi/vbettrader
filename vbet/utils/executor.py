from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, BrokenExecutor, CancelledError
from concurrent.futures.process import BrokenProcessPool
from functools import wraps


def process_exec(executor: ProcessPoolExecutor, task, *args):
    try:
        future = executor.submit(task, *args)
        return future
    except(BrokenProcessPool, BrokenExecutor, CancelledError, KeyboardInterrupt):
        return None


def process_interrupt():
    def _inner(func):
        @wraps(func)
        def _wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except KeyboardInterrupt as err:
                print("okay")
        return _wrapper
