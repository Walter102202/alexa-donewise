"""Local TCP host shared by acceptance tests and sandbox evaluations."""

import socket
import sys
import threading
import time
from contextlib import contextmanager

import uvicorn

# Python 3.12's Windows Proactor can raise WinError 10054 during SSE socket shutdown
# before delivering connection_lost, leaving Uvicorn waiting forever. This HTTP-only
# host needs no subprocess/pipes; use the socket selector loop on Windows.
HTTP_LOOP = "asyncio:SelectorEventLoop" if sys.platform == "win32" else "auto"


@contextmanager
def serving(app):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="on", loop=HTTP_LOOP))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert server.started
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(20)
        sock.close()
        assert not thread.is_alive()
