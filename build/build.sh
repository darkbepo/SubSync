#!/bin/sh
# Builds build/SubSync.exe (window) and build/subsync-cli.exe (command line) from the same launcher code.
set -e
cd "$(dirname "$0")/.."
rm -rf launcher/appfiles && mkdir -p launcher/appfiles/subsync
cp app/*.py launcher/appfiles/
cp app/subsync/*.py launcher/appfiles/subsync/
cd launcher
GOOS=windows GOARCH=amd64 CGO_ENABLED=0 go build -trimpath -ldflags "-s -w -H windowsgui" -o ../build/SubSync.exe .
GOOS=windows GOARCH=amd64 CGO_ENABLED=0 go build -trimpath -ldflags "-s -w -X main.mode=cli" -o ../build/subsync-cli.exe .
ls -la ../build/SubSync.exe ../build/subsync-cli.exe
