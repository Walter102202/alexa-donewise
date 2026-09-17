import json
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import httpx
import pytest
from donewise_adapters.fault_proxy import FaultProxy
from donewise_harness.contracts import FaultKind
from donewise_harness.faults import FaultBoard


@pytest.fixture
def upstream():
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.reply()

        def do_POST(self):
            self.reply()

        def do_PATCH(self):
            self.reply()

        def reply(self):
            body = self.rfile.read(int(self.headers.get("content-length", 0)))
            calls.append((self.command, self.path, dict(self.headers), body))
            data = json.dumps({"id": "pi_local", "livemode": False}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_proxy_faults_on_real_local_http(upstream):
    url, calls = upstream
    faults = FaultBoard()
    faults.active_run = "run_a"
    with httpx.Client(transport=FaultProxy(faults)) as client:
        faults.arm(FaultKind.ACK_WITHOUT_WRITE, "run_a")
        ack = client.post(url + "/v1/payment_intents", data={"amount": 100, "currency": "usd"})
        assert ack.json()["id"].startswith("pi_injected_") and calls == []
        faults.arm(FaultKind.READ_UNAVAILABLE, "run_a")
        assert client.get(url + "/read").status_code == 503 and calls == []
        faults.arm(FaultKind.CONCURRENT_EDIT, "run_a")
        assert client.patch(url + "/event", json={}).status_code == 412 and calls == []
        faults.arm(FaultKind.DROP_RESPONSE_AFTER_WRITE, "run_a")
        with pytest.raises(httpx.ReadError):
            client.post(url + "/write", content=b"unaltered", headers={"Idempotency-Key": "same"})
        assert len(calls) == 1 and calls[0][3] == b"unaltered"
        assert calls[0][2]["Idempotency-Key"] == "same"
        assert client.post(url + "/write", content=b"unaltered").status_code == 200
        assert len(calls) == 2
        assert len(faults.fired("run_a")) == 4 and not faults.armed("run_a")


def test_proxy_run_isolation_and_single_consumption(upstream):
    url, calls = upstream
    faults = FaultBoard()
    faults.arm(FaultKind.READ_UNAVAILABLE, "run_a")
    with httpx.Client(transport=FaultProxy(faults)) as client:

        def read(run):
            faults.active_run = run
            return client.get(url + "/read").status_code

        with ThreadPoolExecutor(max_workers=4) as pool:
            statuses = list(pool.map(read, ["run_b", "run_a", "run_a", "run_b"]))
    assert statuses.count(503) == 1 and len(calls) == 3
    assert faults.fired("run_b") == []
