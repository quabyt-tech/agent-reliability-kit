"""HTTP targets: evaluate an agent over its API instead of importing it."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from agent_reliability_kit.evals import Dataset, EvalCase, EvalHarness, ExactMatchScorer
from agent_reliability_kit.targets import load_target


@pytest.fixture
def agent_url():
    """A stand-in agent API: echoes `message` upper-cased; 500s on 'boom'."""
    seen_auth: list = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen_auth.append(self.headers.get("Authorization"))
            status = 500 if body["message"] == "boom" else 200
            out = json.dumps({"reply": body["message"].upper()}).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/invoke", seen_auth
    server.shutdown()


def test_eval_harness_runs_against_http_target(agent_url, monkeypatch):
    url, seen_auth = agent_url
    monkeypatch.setenv("AR_TARGET_HEADERS", '{"Authorization": "Bearer t"}')
    ds = Dataset(name="d", version="1", cases=[
        EvalCase(id="a", input={"message": "hi"}, expected={"reply": "HI"}),
        EvalCase(id="b", input={"message": "boom"}, expected={"reply": "BOOM"}),
    ])
    harness = EvalHarness(target=load_target(url), scorers=[ExactMatchScorer("reply")])
    result = harness.run(ds)
    assert result.passed == 1 and result.errored == 1
    assert seen_auth[0] == "Bearer t"



def test_load_target_rejects_bad_spec():
    with pytest.raises(ValueError):
        load_target("not-a-spec")
