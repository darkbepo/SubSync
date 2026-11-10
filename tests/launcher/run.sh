#!/usr/bin/env bash
# Launcher tests: runs the real SubSync.exe / subsync-cli.exe under Wine against a fake internet.
# Needs: Linux, wine (64-bit), Xvfb, Go >= 1.24, python3.   Work folder: $WORK (default /tmp/subsync-launcher-test)
# Exit code 0 = all checks passed.
set -u
REPO=$(cd "$(dirname "$0")/../.." && pwd)
WORK=${WORK:-/tmp/subsync-launcher-test}
export WINEPREFIX=$WORK/wineprefix WINEDEBUG=-all DISPLAY=${DISPLAY:-:99}
PASS=0; FAIL=0
check() { if eval "$2"; then echo "  PASS  $1"; PASS=$((PASS+1)); else echo "  FAIL  $1"; FAIL=$((FAIL+1)); fi; }
live() { ps -eo stat,args | grep -iE '[p]ython(w)?\.exe' | grep -vc '^Z'; }       # app processes still alive
settle() { for _ in $(seq 1 20); do [ "$(live)" = 0 ] && return 0; sleep 1; done; return 1; }
gui() { rm -f cache/window-ready.flag; : > "$WORK/requests.log"; timeout "${1:-180}" wine SubSync.exe >/dev/null 2>&1; }

echo "== preparing (work folder: $WORK)"
rm -rf "$WORK"; mkdir -p "$WORK"
pgrep -x Xvfb >/dev/null || { Xvfb "$DISPLAY" -screen 0 1280x800x24 >/dev/null 2>&1 & sleep 1; }
wineboot -i >/dev/null 2>&1
# a fake NVIDIA driver, so the GPU-library path is exercised
cp "$WINEPREFIX/drive_c/windows/system32/version.dll" "$WINEPREFIX/drive_c/windows/system32/nvcuda.dll"
(cd "$REPO/tests/launcher/fake_app" && GOOS=windows CGO_ENABLED=0 go build -o "$WORK/fake_app.exe" .) || exit 1
python3 "$REPO/tests/launcher/make_fixtures.py" "$WORK" "$WORK/fake_app.exe" >/dev/null || exit 1
# both programs, built with the test manifest (all primary links dead)
rm -rf "$WORK/lt" && cp -r "$REPO/launcher" "$WORK/lt" && cp "$WORK/manifest.json" "$WORK/lt/manifest.json"
rm -rf "$WORK/lt/appfiles" && mkdir -p "$WORK/lt/appfiles/subsync"
cp "$REPO"/app/*.py "$WORK/lt/appfiles/" && cp "$REPO"/app/subsync/*.py "$WORK/lt/appfiles/subsync/"
D=$WORK/SubSync; mkdir -p "$D"
(cd "$WORK/lt" && GOOS=windows CGO_ENABLED=0 go build -ldflags "-H windowsgui" -o "$D/SubSync.exe" . \
  && GOOS=windows CGO_ENABLED=0 go build -ldflags "-X main.mode=cli" -o "$D/subsync-cli.exe" .) || exit 1
cp "$WORK/sources.json" "$D/"
python3 "$REPO/tests/launcher/fake_server.py" "$WORK" >"$WORK/server.out" 2>&1 &
SERVER=$!
trap 'kill $SERVER 2>/dev/null; wineserver -k 2>/dev/null' EXIT
sleep 1
cd "$D" || exit 1

echo "== A. first install with every primary link dead"
echo -n normal > mode.txt; gui 300
check "install completes from fallback sources; app launched"   '[ -f cache/window-ready.flag ]'
check "Python taken from the NuGet layout (no pythonw.exe)"      '[ -f runtime/python/python.exe ] && grep -q "^Lib" runtime/python/python312._pth'
check "one consistent C++ runtime set applied after Python"      '[ "$(cat runtime/python/vcruntime140.dll)" = NEW ]'
check "GPU DLLs extracted, nvblas skipped"                       '[ -f runtime/cuda/cudnn_ops64_9.dll ] && [ ! -e runtime/cuda/nvblas64_12.dll ]'
check "models pinned to an exact revision"                       'grep -q aaaa1111 runtime/models.lock.json && grep -q cccc3333 runtime/models.lock.json'
check "nothing left running after the app closes"                settle

echo "== B. start with an intact install"
gui 60
check "self-check passes, nothing downloaded"                    '[ ! -s "$WORK/requests.log" ]'

echo "== C. damaged files are repaired, nothing else"
rm runtime/python/Lib/site-packages/faster_whisper/transcribe.py
head -c 1000 runtime/cuda/cudnn_ops64_9.dll > x.tmp && mv x.tmp runtime/cuda/cudnn_ops64_9.dll
rm models/whisper-large-v3-turbo/model.bin app/subsync/align.py
gui 180
check "deleted library file restored"                            '[ -f runtime/python/Lib/site-packages/faster_whisper/transcribe.py ]'
check "truncated GPU DLL restored"                               '[ "$(stat -c%s runtime/cuda/cudnn_ops64_9.dll)" = 3000000 ]'
check "deleted model file restored (same revision)"              '[ "$(head -c1 models/whisper-large-v3-turbo/model.bin)" = A ]'
check "deleted app file restored from the exe"                   '[ -f app/subsync/align.py ]'
check "intact parts were not downloaded again"                   '! grep -qE "big_lib|/py/|minilm|MiniLM" "$WORK/requests.log"'
check "repair logged"                                            'grep -q "self-check: re-downloading" logs/setup.log'

echo "== D. a pinned model repository disappears"
echo "mobiuslabsgmbh/faster-whisper-large-v3-turbo" > "$WORK/gone.txt"; rm models/whisper-large-v3-turbo/model.bin
gui 180; rm -f "$WORK/gone.txt"
check "model re-installed from the backup repository"            '[ "$(head -c1 models/whisper-large-v3-turbo/model.bin)" = B ]'
check "lock now points at the backup repository"                 'grep -q bbbb2222 runtime/models.lock.json'

echo "== E. processes"
echo -n stay > mode.txt; (wine SubSync.exe >/dev/null 2>&1 &); sleep 6
check "app and its helper are running"                           '[ "$(live)" -ge 2 ]'
s=$(date +%s); timeout 30 wine SubSync.exe >/dev/null 2>&1
check "second start only focuses the open window"                '[ $(( $(date +%s) - s )) -lt 15 ]'
pkill -9 -f 'SubSync.exe'
check "killing the launcher ends app + helper"                   settle
echo -n crash > mode.txt; (timeout 40 wine SubSync.exe >/dev/null 2>&1 &); sleep 10
check "crash before the window: nothing left while error shows"  '[ "$(live)" = 0 ]'
pkill -9 -f 'SubSync.exe'; sleep 1
# leftovers from an older version (not in any job) are ended at the next start
echo -n normal > mode.txt
(wine start /unix "$D/runtime/python/python.exe" --helper >/dev/null 2>&1 &); sleep 4
gui 60
check "stray processes from older versions cleaned up"           settle

echo "== F. command line"
wine subsync-cli.exe help >/dev/null 2>&1;                  check "help -> exit 0"                  '[ $? -eq 0 ]'
wine subsync-cli.exe check >/dev/null 2>&1;                 check "check (intact) -> exit 0"        '[ $? -eq 0 ]'
rm models/minilm/tokenizer.json
wine subsync-cli.exe check >/dev/null 2>&1;                 check "check (damaged) -> exit 8"       '[ $? -eq 8 ]'
echo -n exit3 > mode.txt; mkdir -p "$WORK/My Shows"
out=$(cd "$WORK/My Shows" && wine "$D/subsync-cli.exe" sync . --suffix eng 2>&1); code=$?
check "sync repairs first, then passes exit code 3 through"      '[ $code -eq 3 ] && [ -f models/minilm/tokenizer.json ]'
check "arguments and working folder reach the app"               'echo "$out" | grep -q "sync . --suffix eng" && echo "$out" | grep -q "My Shows"'
echo -n crash > mode.txt
wine subsync-cli.exe . >/dev/null 2>&1;                     check "app crash -> exit 10"            '[ $? -eq 10 ]'
wine subsync-cli.exe frobnicate >/dev/null 2>&1;            check "unknown command -> exit 6"       '[ $? -eq 6 ]'
check "nothing left running after the CLI"                       settle

echo "== $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
