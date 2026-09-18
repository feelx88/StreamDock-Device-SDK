from threading import Thread, Lock
from contextlib import contextmanager


class Lockable:

    def __init__(self, locks):
        self._locks = locks

    @contextmanager
    def _acquire_timeout(self, lock):
        result = self._locks[lock].acquire(timeout=0.1)
        try:
            yield result
        finally:
            if result:
                self._locks[lock].release()
