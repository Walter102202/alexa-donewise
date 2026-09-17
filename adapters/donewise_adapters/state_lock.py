"""Serialize read/modify/write of each local fake store across worker threads."""

from functools import wraps


def locked(fn):
    @wraps(fn)
    def call(self, *args, **kwargs):
        with self._lock:
            return fn(self, *args, **kwargs)

    return call
