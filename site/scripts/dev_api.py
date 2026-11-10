"""A stand-in for the JSON API in docs/ARCHITECTURE.md section 8, over the fixture corpus.

    uv run python site/scripts/dev_api.py [port]

Search here is a naive keyword match (see standin.py). Quote checks and answer audits are
the core library's own. Set PUBLIC_API_BASE to the real server when it exists.
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from standin import library, search

from onthepage.corpus import CorpusError
from onthepage.ids import IdError
from onthepage.quote import QuoteTooShortError

CORPUS = library()


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: object) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "content-type")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self) -> None:
        self._send(204, {})

    def do_GET(self) -> None:
        url = urlparse(self.path)
        params = {k: v[0] for k, v in parse_qs(url.query).items()}
        try:
            if url.path == "/api/search":
                self._send(200, search(CORPUS, params.get("query", ""), limit=int(params.get("limit", 10)), doc=params.get("doc")))
            elif url.path.startswith("/api/doc/"):
                ns, rest = url.path.removeprefix("/api/doc/").split("/", 1)
                self._send(200, CORPUS.document_card(f"{ns}:{rest}").model_dump(mode="json"))
            else:
                self._send(404, {"error": "no such route"})
        except (CorpusError, IdError, ValueError) as exc:
            self._send(400, {"error": str(exc)})

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        try:
            if self.path == "/api/verify":
                check = CORPUS.verify_quote(body["quote"], body["cite"])
                self._send(200, check.model_dump(mode="json"))
            elif self.path == "/api/check":
                self._send(200, CORPUS.check_answer(body["text"]).model_dump(mode="json"))
            else:
                self._send(404, {"error": "no such route"})
        except (CorpusError, IdError, QuoteTooShortError, KeyError, ValueError) as exc:
            self._send(400, {"error": str(exc)})

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8791
    print(f"stand-in API on http://127.0.0.1:{port}")
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
