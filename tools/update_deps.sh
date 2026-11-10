#!/usr/bin/env bash
# Regenerates launcher/manifest.json from tools/requirements-windows.txt and tools/requirements-cuda.txt:
# resolves the exact win_amd64/cp312 wheels with pip (no install), records URL + SHA-256 + size, downloads
# the CUDA wheels once to record the DLL names/sizes the self-check needs.
# Needs: python3 + pip with internet access to pypi.org. Afterwards: re-check CLAUDE.md lessons 3 and 5.
set -euo pipefail
REPO=$(cd "$(dirname "$0")/.." && pwd)
TMP=${TMP_DIR:-$(mktemp -d)}
mkdir -p "$TMP"
PIPWIN=(--dry-run --ignore-installed --only-binary=:all: --platform win_amd64 --python-version 3.12
        --implementation cp --abi cp312 --target "$TMP/target" -q)
pip install "${PIPWIN[@]}" -r "$REPO/tools/requirements-windows.txt" --report "$TMP/win.json"
pip install "${PIPWIN[@]}" -r "$REPO/tools/requirements-cuda.txt" --report "$TMP/cuda.json"
mkdir -p "$TMP/cudawheels"
python3 - "$TMP/cuda.json" "$TMP/cudawheels" <<'PY'
import hashlib, json, os, sys, urllib.request
def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()
for i in json.load(open(sys.argv[1]))["install"]:
    url = i["download_info"]["url"]; want = i["download_info"]["archive_info"]["hashes"]["sha256"]
    dst = os.path.join(sys.argv[2], url.split("/")[-1])
    if os.path.exists(dst) and sha(dst) == want:
        continue                                   # already here and verified
    print("downloading", os.path.basename(dst))
    urllib.request.urlretrieve(url, dst + ".part")  # never leave a half file under the real name
    if sha(dst + ".part") != want:
        sys.exit(f"checksum mismatch for {os.path.basename(dst)}")
    os.replace(dst + ".part", dst)
PY
python3 "$REPO/tools/make_manifest.py" "$TMP/win.json" "$TMP/cuda.json" "$REPO/launcher/manifest.json" "$TMP/cudawheels"
echo "launcher/manifest.json updated (work files in $TMP)"
