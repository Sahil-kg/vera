"""Dependency-free HTTP server for the magicpin challenge endpoints.
Run:
	python -m bot.server

This module delegates all challenge logic to the `bot` package.
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from . import CONTEXTS, CONVERSATIONS, MERCHANT_AUTO_REPLY_COUNTS, SENT_SUPPRESSIONS
from . import healthz, metadata, push_context, reply, tick, utc_now, clear_insight_cache

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8080"))
MAX_REQUEST_BYTES = int(os.getenv("MAX_REQUEST_BYTES", str(500 * 1024)))


class Handler(BaseHTTPRequestHandler):
	server_version = "VeraPrecisionBot/1.0"

	def _json(self, status: int, payload: dict[str, Any]) -> None:
		body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
		self.send_response(status)
		self.send_header("Content-Type", "application/json; charset=utf-8")
		self.send_header("Content-Length", str(len(body)))
		self.end_headers()
		self.wfile.write(body)

	def _read_json(self) -> dict[str, Any] | None:
		try:
			length = int(self.headers.get("Content-Length", "0"))
			if length > MAX_REQUEST_BYTES:
				return {"__error__": "payload_too_large"}
			raw = self.rfile.read(length) if length else b"{}"
			return json.loads(raw.decode("utf-8"))
		except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
			return None

	def do_GET(self) -> None:
		path = urlparse(self.path).path

		if path == "/v1/healthz":
			self._json(200, healthz())

		elif path == "/v1/metadata":
			self._json(200, metadata())

		elif path == "/debug/suppressions":
			self._json(
				200,
				{
					"count": len(SENT_SUPPRESSIONS),
					"keys": list(SENT_SUPPRESSIONS)[:20],
				},
			)

		elif path == "/debug/state":
			self._json(
				200,
				{
					"contexts": len(CONTEXTS),
					"conversations": len(CONVERSATIONS),
					"suppressions": len(SENT_SUPPRESSIONS),
					"auto_reply_counts": len(MERCHANT_AUTO_REPLY_COUNTS),
				},
			)
		elif path == "/debug/contexts":
			summary = {}
			for (scope, cid), entry in CONTEXTS.items():
				p = entry.get("payload", {})
				summary.setdefault(scope, []).append({
					"context_id": cid,
					"merchant_id": p.get("merchant_id"),
					"category_slug": p.get("slug") or p.get("category_slug"),
				})
			self._json(200, summary)

		elif path == "/v1/tick":
			data = self._read_json() or {}
			print(f"[tick] available_triggers={data.get('available_triggers', [])}")
			print(f"[tick] stored_scopes={ {s: [c for (s2,c) in CONTEXTS if s2==s] for s in ['merchant','category','trigger']} }")
			self._json(200, tick(str(data.get("now", utc_now())), list(data.get("available_triggers", []))))
		else:
			self._json(404, {"error": "not_found"})

	def do_POST(self) -> None:
		path = urlparse(self.path).path
		print(f"[POST] {path}")
		data = self._read_json()
		if data is None:
			self._json(400, {"accepted": False, "reason": "invalid_json"})
			return
		if data.get("__error__") == "payload_too_large":
			self._json(413, {"accepted": False, "reason": "payload_too_large", "max_bytes": MAX_REQUEST_BYTES})
			return

		if path == "/v1/context":
			missing = [k for k in ("scope", "context_id", "version", "payload") if k not in data]
			if missing:
				self._json(400, {"accepted": False, "reason": "missing_fields", "details": missing})
				return
			status, payload = push_context(
				str(data["scope"]),
				str(data["context_id"]),
				int(data["version"]),
				data["payload"],
			)
			self._json(status, payload)
		elif path == "/v1/tick":
			self._json(200, tick(str(data.get("now", utc_now())), list(data.get("available_triggers", []))))
		elif path == "/v1/reply":
			required = ["conversation_id", "message"]
			missing = [k for k in required if k not in data]
			if missing:
				self._json(400, {"action": "end", "rationale": f"missing fields: {missing}"})
				return
			self._json(
				200,
				reply(
					str(data["conversation_id"]),
					data.get("merchant_id"),
					data.get("customer_id"),
					str(data["message"]),
					int(data.get("turn_number", 0)),
				),
			)
		elif path == "/v1/teardown":
			CONTEXTS.clear()
			CONVERSATIONS.clear()
			SENT_SUPPRESSIONS.clear()
			MERCHANT_AUTO_REPLY_COUNTS.clear()
			clear_insight_cache() 
			self._json(200, {"accepted": True, "wiped": True})
		else:
			self._json(404, {"error": "not_found"})

	def log_message(self, fmt: str, *args: Any) -> None:
		print("%s - %s" % (self.address_string(), fmt % args))


def main() -> None:
	httpd = ThreadingHTTPServer((HOST, PORT), Handler)
	print(f"Vera Precision Bot listening on http://{HOST}:{PORT}")
	httpd.serve_forever()


if __name__ == "__main__":
	main()
