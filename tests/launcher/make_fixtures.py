"""Builds the fake download world for launcher tests: a Python package in NuGet layout (no pythonw.exe),
three wheels with real RECORD files, a GPU wheel, three model repositories, a PEP 503 index, plus a test
manifest whose primary links are all dead and a sources.json pointing at the fake server.
Usage: python make_fixtures.py <work folder> <fake_app.exe>"""
import hashlib, io, json, os, shutil, zipfile
import sys
WORK = sys.argv[1]                      # test work folder
FAKEAPP = sys.argv[2]                   # built fake_app .exe
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
R = WORK + "/srv"; shutil.rmtree(R, ignore_errors=True)
for d in ("py", "files", "hf"): os.makedirs(f"{R}/{d}")
sha = lambda b: hashlib.sha256(b).hexdigest()
fakeapp = open(FAKEAPP, "rb").read()
# Python only via NuGet layout (tools/), and without pythonw.exe -> tests python.exe fallback
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as z:
    z.writestr("python.nuspec", "x"); z.writestr("tools/python.exe", fakeapp); z.writestr("tools/python312.dll", b"d" * 5000)
    z.writestr("tools/python3.dll", b"d"); z.writestr("tools/vcruntime140.dll", "OLD"); z.writestr("tools/Lib/os.py", "#")
open(f"{R}/py/python.3.12.10.nupkg", "wb").write(buf.getvalue())
def wheel(fname, files):
    name, ver = fname.split("-")[:2]
    buf = io.BytesIO(); rec = []
    with zipfile.ZipFile(buf, "w") as z:
        for n, d in files.items():
            d = d if isinstance(d, bytes) else d.encode(); z.writestr(n, d); rec.append(f"{n},sha256=x,{len(d)}")
        rec.append(f"{name}-{ver}.dist-info/RECORD,,"); z.writestr(f"{name}-{ver}.dist-info/RECORD", "\n".join(rec) + "\n")
    data = buf.getvalue(); open(f"{R}/files/{fname}", "wb").write(data); return data
idx = {}; wheels = []
for fname, files in [("faster_whisper-1.2.1-py3-none-any.whl", {"faster_whisper/__init__.py": "#", "faster_whisper/transcribe.py": "x" * 3000}),
                     ("msvc_runtime-14.51-cp312-cp312-win_amd64.whl", {"msvc_runtime.pyd": "p", "msvc_runtime-14.51.data/data/msvcp140.dll": "NEW",
                      "msvc_runtime-14.51.data/data/Scripts/vcruntime140.dll": "NEW", "msvc_runtime-14.51.data/data/Scripts/x.txt": "skip"}),
                     ("big_lib-1.0-cp312-cp312-win_amd64.whl", {"big_lib/data.bin": os.urandom(8_000_000), "big_lib/__init__.py": "#"})]:
    d = wheel(fname, files); proj = fname.split("-")[0].lower().replace("_", "-")
    idx.setdefault(proj, []).append((fname, sha(d)))
    wheels.append({"name": f"{proj} {fname.split('-')[1]}", "url": f"https://dead.example.invalid/packages/{fname}", "sha256": sha(d), "size": len(d), "kind": "wheel"})
cbuf = io.BytesIO(); cdll = os.urandom(3_000_000)
with zipfile.ZipFile(cbuf, "w") as z: z.writestr("nvidia/cudnn/bin/cudnn_ops64_9.dll", cdll); z.writestr("nvidia/cudnn/bin/nvblas64_12.dll", "n")
cd = cbuf.getvalue(); open(f"{R}/files/nvidia_cudnn_cu12-9.10.2.21-py3-none-win_amd64.whl", "wb").write(cd)
idx["nvidia-cudnn-cu12"] = [("nvidia_cudnn_cu12-9.10.2.21-py3-none-win_amd64.whl", sha(cd))]
cuda = [{"name": "nvidia-cudnn-cu12 9.10.2.21", "url": "https://dead.example.invalid/packages/nvidia_cudnn_cu12-9.10.2.21-py3-none-win_amd64.whl",
         "sha256": sha(cd), "size": len(cd), "kind": "cuda", "files": [{"name": "cudnn_ops64_9.dll", "size": len(cdll)}]}]
json.dump(idx, open(f"{R}/index.json", "w"))
def repo(name, rev, files):
    base = f"{R}/hf/{name}"; os.makedirs(base + "/files/onnx", exist_ok=True); open(base + "/REV", "w").write(rev); tree = []
    for p, d in files.items():
        open(f"{base}/files/{p}", "wb").write(d); e = {"type": "file", "path": p, "size": len(d)}
        if len(d) > 1000: e["lfs"] = {"oid": sha(d), "size": len(d)}
        tree.append(e)
    tree.append({"type": "directory", "path": "onnx"}); json.dump(tree, open(base + "/tree.json", "w"))
wfiles = {"config.json": b"{}", "preprocessor_config.json": b"{}", "tokenizer.json": b"{}", "vocabulary.json": b"{}"}
repo("mobiuslabsgmbh/faster-whisper-large-v3-turbo", "aaaa1111", {**wfiles, "model.bin": b"A" * 6_000_000})
repo("deepdml/faster-whisper-large-v3-turbo-ct2", "bbbb2222", {**wfiles, "model.bin": b"B" * 5_000_000})
repo("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", "cccc3333", {"onnx/model_quint8_avx2.onnx": os.urandom(2_000_000), "tokenizer.json": b"{}"})
m = json.load(open(REPO + "/launcher/manifest.json"))
m["python"] = {**m["python"], "url": "https://dead.example.invalid/python-3.12.10-embed-amd64.zip", "fallbacks": [], "sha256": "", "size": 0}
m["wheels"], m["cuda"] = wheels, cuda
json.dump(m, open(WORK + "/manifest.json", "w"), indent=1)
json.dump({"python_urls": ["http://127.0.0.1:8766/py/missing.zip", "http://127.0.0.1:8766/py/python.3.12.10.nupkg"],
           "pypi_indexes": ["http://127.0.0.1:8766/simple"], "hf_hosts": ["http://127.0.0.1:8766/hf"]}, open(WORK + "/sources.json", "w"))
print("fixtures ready")
