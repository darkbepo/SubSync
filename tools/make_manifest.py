"""Build-time: turn pip resolver reports into the launcher's download manifest."""
import json, sys, urllib.request

def sizes_for(name, version):
    d = json.load(urllib.request.urlopen(f"https://pypi.org/pypi/{name}/{version}/json"))
    return {f["filename"]: f["size"] for f in d["urls"]}

def entries(report, kind):
    out = []
    for i in json.load(open(report))["install"]:
        m, d = i["metadata"], i["download_info"]
        fn = d["url"].split("/")[-1]
        size = sizes_for(m["name"], m["version"])[fn]
        out.append({"name": f'{m["name"]} {m["version"]}', "url": d["url"],
                    "sha256": d["archive_info"]["hashes"]["sha256"], "size": size, "kind": kind})
    return out

manifest = {
    "python": {"name": "Python 3.12.10", "kind": "python", "version": "3.12.10",
               "url": "https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip",
               "fallbacks": ["https://api.nuget.org/v3-flatcontainer/python/3.12.10/python.3.12.10.nupkg"],
               "sha256": "", "size": 0},
    "wheels": entries(sys.argv[1], "wheel"),
    "cuda": entries(sys.argv[2], "cuda"),
    "models": [
        {"name": "speech recognition model", "kind": "hf",
         "dest": "models/whisper-large-v3-turbo",
         "candidates": [{"repo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
                          "files": ["config.json", "preprocessor_config.json", "model.bin", "tokenizer.json", "vocabulary.*"]},
                        {"repo": "deepdml/faster-whisper-large-v3-turbo-ct2",
                          "files": ["config.json", "preprocessor_config.json", "model.bin", "tokenizer.json", "vocabulary.*"]}]},
        {"name": "matching model", "kind": "hf",
         "dest": "models/minilm",
         "candidates": [{"repo": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
                          "files": ["onnx/model_quint8_avx2.onnx=model.onnx", "tokenizer.json"]},
                        {"repo": "Xenova/paraphrase-multilingual-MiniLM-L12-v2",
                          "files": ["onnx/model_quantized.onnx=model.onnx", "tokenizer.json"]}]},
    ],
}
# exact DLL names/sizes of the GPU libraries, for the self-check (argv[4] = folder with the CUDA wheels)
import os, zipfile
for c in manifest["cuda"]:
    z = zipfile.ZipFile(os.path.join(sys.argv[4], c["url"].split("/")[-1]))
    c["files"] = [{"name": os.path.basename(i.filename), "size": i.file_size} for i in z.infolist()
                  if "/bin/" in i.filename and i.filename.lower().endswith(".dll")
                  and not os.path.basename(i.filename).startswith("nvblas") and ".alt." not in i.filename]
json.dump(manifest, open(sys.argv[3], "w"), indent=1)
tot = lambda k: sum(e["size"] for e in manifest[k]) / 1e6
print(f"wheels {len(manifest['wheels'])} = {tot('wheels'):.0f} MB, cuda = {tot('cuda'):.0f} MB")
