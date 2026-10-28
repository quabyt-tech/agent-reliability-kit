"""Serve the agent over HTTP, so the same suites can run against a URL:

    uv run python serve.py
    uv run arkit run adversarial.jsonl -t http://localhost:8000/agent -s scorers:ADVERSARIAL
"""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from agent import run


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/agent":
            self.send_error(404)
            return
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        body = json.dumps(run(payload)).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    print("Listening on http://localhost:8000/agent")
    ThreadingHTTPServer(("localhost", 8000), Handler).serve_forever()
