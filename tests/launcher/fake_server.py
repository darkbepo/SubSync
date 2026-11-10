"""Fake internet for launcher tests: Python host (/py), PEP 503 index (/simple, /files) and the Hugging Face
API (/hf). Supports HTTP Range (resume) and logs every request path to <work>/requests.log.
Usage: python fake_server.py <work folder>   (listens on 127.0.0.1:8766)"""
import http.server, json, os, re, socketserver, sys, time
WORK = sys.argv[1]
ROOT = WORK + "/srv"; LOG = WORK + "/requests.log"; GONE_FILE = WORK + "/gone.txt"
GONE = lambda: set(open(GONE_FILE).read().split()) if os.path.exists(GONE_FILE) else set()  # repos that "disappeared"
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def send_file(self, p):
        if not os.path.isfile(p): return self.err(404)
        size = os.path.getsize(p); start = 0
        m = re.match(r"bytes=(\d+)-", self.headers.get("Range", ""))
        if m: start = int(m.group(1)); self.send_response(206); self.send_header("Content-Range", f"bytes {start}-{size-1}/{size}")
        else: self.send_response(200)
        self.send_header("Content-Length", str(size - start)); self.end_headers()
        if self.command == "HEAD": return
        with open(p, "rb") as f:
            f.seek(start)
            while c := f.read(1 << 16):
                self.wfile.write(c); time.sleep(len(c) / 40e6)
    def err(self, code): self.send_response(code); self.send_header("Content-Length", "0"); self.end_headers()
    def body(self, s, ctype="application/json"):
        b = s.encode(); self.send_response(200); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_HEAD(self): self.do_GET()
    def do_GET(self):
        p = self.path.split("?")[0]
        open(LOG, "a").write(p + "\n")
        if p.startswith("/py/"): return self.send_file(ROOT + "/py/" + os.path.basename(p))
        if p.startswith("/files/"): return self.send_file(ROOT + "/files/" + os.path.basename(p))
        m = re.match(r"/simple/([^/]+)/$", p)
        if m:
            idx = json.load(open(ROOT + "/index.json"))
            links = "".join(f'<a href="../../files/{f}#sha256={h}">{f}</a>\n' for f, h in idx.get(m.group(1), []))
            return self.body(f"<html><body>{links}</body></html>", "text/html")
        m = re.match(r"/hf/api/models/(.+?)/revision/main$", p)
        if m:
            repo = m.group(1)
            if repo in GONE() or not os.path.isdir(f"{ROOT}/hf/{repo}"): return self.err(404)
            return self.body(json.dumps({"sha": open(f"{ROOT}/hf/{repo}/REV").read().strip()}))
        m = re.match(r"/hf/api/models/(.+?)/tree/([0-9a-f]+)$", p)
        if m:
            repo = m.group(1)
            if repo in GONE(): return self.err(404)
            return self.body(open(f"{ROOT}/hf/{repo}/tree.json").read())
        m = re.match(r"/hf/(.+?)/resolve/([0-9a-f]+)/(.+)$", p)
        if m:
            repo, rev, fp = m.groups()
            if repo in GONE(): return self.err(404)
            return self.send_file(f"{ROOT}/hf/{repo}/files/{fp}")
        self.err(404)
class S(socketserver.ThreadingMixIn, http.server.HTTPServer): daemon_threads = True; allow_reuse_address = True
S(("127.0.0.1", 8766), H).serve_forever()
