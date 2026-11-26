#!/usr/bin/env python3
"""
OpenAI-compatible embedding service for bge-small-en-v1.5 (GGUF, CPU).

Serves /v1/embeddings for OpenViking. Stdlib-only: the only dependency is
llama-cpp-python (in the ~/.openviking/venv).

v2 (2026-11-22, rebuilt after the Nov-16 setup kept dying):
- Model loads at STARTUP, before the server accepts traffic — /health is
  accurate from the first probe, and there is no slow/hanging first request
  (the old lazy load was the main failure mode).
- Served under a systemd user service with Restart=always, so a crash is
  recovered automatically instead of silently killing OpenViking ingestion.
- Port 8091 (the old 8001 collided with the small-brain vLLM endpoint).

Pooling: if the GGUF declares MEAN/CLS pooling, llama-cpp returns a single
vector; if NONE, we mean-pool the token vectors ourselves and L2-normalize.
BGE convention: L2-normalized embeddings (cosine similarity).
"""
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from llama_cpp import Llama

MODEL_PATH = os.path.expanduser("~/.openviking/models/bge-small-en-v1.5-f16.gguf")
MODEL_ID = "bge-small-en-v1.5"
HOST = "127.0.0.1"
PORT = 8091
MAX_BATCH = 512

_model = None
_model_lock = threading.Lock()
_embed_lock = threading.Lock()


def load_model() -> Llama:
    global _model
    with _model_lock:
        if _model is None:
            t0 = time.time()
            print(f"loading embedding model from {MODEL_PATH} ...", flush=True)
            _model = Llama(
                model_path=MODEL_PATH,
                embedding=True,
                n_threads=8,
                n_gpu_layers=0,  # CPU only — zero VRAM, GPUs untouched
                verbose=False,
            )
            print(f"embedding model ready in {time.time() - t0:.1f}s", flush=True)
    return _model


def _mean_pool(token_vectors):
    """Mean-pool per-token vectors and L2-normalize (BGE convention)."""
    n = len(token_vectors)
    mean = [sum(t) / n for t in zip(*token_vectors)]
    norm = (sum(v * v for v in mean) ** 0.5) or 1.0
    return [v / norm for v in mean]


def embed_one(text: str):
    m = _model
    with _embed_lock:
        r = m.embed(text, normalize=True)
    # r is a single vector (MEAN/CLS pooling) or a list of token vectors (NONE)
    if isinstance(r, list) and r and isinstance(r[0], list):
        return _mean_pool(r)
    return r


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._send(200, {"status": "ok", "model": MODEL_ID, "ready": _model is not None})
        elif self.path == "/v1/models":
            self._send(200, {"data": [{"id": MODEL_ID, "object": "model"}]})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/v1/embeddings":
            self._send(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            req = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._send(400, {"error": "invalid json"})
            return
        inp = req.get("input", [])
        if isinstance(inp, str):
            inp = [inp]
        if not isinstance(inp, list) or not inp:
            self._send(400, {"error": "input must be a non-empty string or list"})
            return
        data = []
        for i, text in enumerate(inp[:MAX_BATCH]):
            data.append({"object": "embedding", "embedding": embed_one(text), "index": i})
        total_tokens = sum(max(1, len(t) // 4) for t in inp[:MAX_BATCH])
        self._send(200, {
            "object": "list",
            "data": data,
            "model": req.get("model", MODEL_ID),
            "usage": {"prompt_tokens": total_tokens, "total_tokens": total_tokens},
        })

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


def main():
    # Load before serving: /health is truthful from the first probe.
    load_model()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"embedding service listening on http://{HOST}:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
