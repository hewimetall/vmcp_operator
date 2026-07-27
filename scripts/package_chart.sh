#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$ROOT/dist/charts}"
mkdir -p "$OUT"
helm lint "$ROOT/charts/vmcp-operator"
helm package "$ROOT/charts/vmcp-operator" --destination "$OUT"
echo "packaged charts into $OUT"
ls -la "$OUT"
