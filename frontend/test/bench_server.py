#!/usr/bin/env python3
"""Servidor estático + endpoint de telemetria para o bench.html (Fase 0 PoC).

GET  /...   serve os arquivos estáticos desta pasta, com suporte a `Range`
            (obrigatório para o <video> conseguir buscar (seek) direto num
            ponto do arquivo — SimpleHTTPRequestHandler puro não suporta isso,
            e sem ele o navegador não consegue pular pra um byte-offset
            específico ao arrastar a barra de tempo).
POST /log   corpo JSON com uma amostra do HUD -> acrescenta 1 linha em
            bench_results.ndjson (mesma pasta), para leitura posterior.

Uso: python3 bench_server.py [porta]  (padrão 8123)
"""
import json
import os
import pathlib
import re
import socketserver
import sys
import time
from http.server import SimpleHTTPRequestHandler

ROOT = pathlib.Path(__file__).resolve().parent
LOG_PATH = ROOT / "bench_results.ndjson"
MAX_BODY_BYTES = 8192
RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")


class Handler(SimpleHTTPRequestHandler):
    def send_head(self):
        path = self.translate_path(self.path)
        if not os.path.isfile(path):
            return super().send_head()

        range_header = self.headers.get("Range")
        try:
            f = open(path, "rb")
        except OSError:
            self.send_error(404, "Arquivo não encontrado")
            return None

        file_len = os.fstat(f.fileno()).st_size
        start, end = 0, file_len - 1
        status = 200

        if range_header:
            match = RANGE_RE.fullmatch(range_header.strip())
            if match:
                start_s, end_s = match.groups()
                start = int(start_s) if start_s else 0
                end = int(end_s) if end_s else file_len - 1
                if start > end or start >= file_len:
                    f.close()
                    self.send_error(416, "Range não satisfazível")
                    self.send_header("Content-Range", f"bytes */{file_len}")
                    return None
                end = min(end, file_len - 1)
                status = 206

        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{file_len}")
        self.end_headers()

        f.seek(start)
        self._range_remaining = length
        return f

    def copyfile(self, source, outputfile):
        remaining = getattr(self, "_range_remaining", None)
        if remaining is None:
            super().copyfile(source, outputfile)
            return
        bufsize = 64 * 1024
        while remaining > 0:
            chunk = source.read(min(bufsize, remaining))
            if not chunk:
                break
            outputfile.write(chunk)
            remaining -= len(chunk)
        del self._range_remaining

    def do_POST(self):
        if self.path != "/log":
            self.send_error(404)
            return

        length = int(self.headers.get("Content-Length", 0))
        if length <= 0 or length > MAX_BODY_BYTES:
            self.send_error(400, "corpo ausente ou grande demais")
            return

        try:
            sample = json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            self.send_error(400, "JSON inválido")
            return

        sample["_receivedAt"] = time.time()
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(sample, ensure_ascii=False) + "\n")

        self.send_response(204)
        self.end_headers()

    def log_message(self, fmt, *args):
        pass  # o ndjson já registra o que importa; silencia o access log no stdout


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8123
    with Server(("127.0.0.1", port), Handler) as httpd:
        print(f"servindo {ROOT} em http://127.0.0.1:{port}  (log: {LOG_PATH.name})")
        httpd.serve_forever()
