#!/usr/bin/env bash
# Prove OCI chart push/pull against a local registry (no org credentials required).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REG_NAME="${REG_NAME:-vmcp-local-registry}"
REG_PORT="${REG_PORT:-5001}"
OUT="$ROOT/dist/charts"

mkdir -p "$OUT"
helm lint "$ROOT/charts/vmcp-operator"
helm package "$ROOT/charts/vmcp-operator" --destination "$OUT"
CHART_TGZ="$(ls -1 "$OUT"/vmcp-operator-*.tgz | sort | tail -1)"

if ! sudo docker inspect "$REG_NAME" >/dev/null 2>&1; then
  sudo docker run -d --name "$REG_NAME" -p "${REG_PORT}:5000" registry:2
else
  sudo docker start "$REG_NAME" >/dev/null
fi

# Wait for registry
for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:${REG_PORT}/v2/" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

echo "Pushing $CHART_TGZ to oci://127.0.0.1:${REG_PORT}/charts"
# Local registry speaks HTTP; Helm 4 requires --plain-http.
helm push "$CHART_TGZ" "oci://127.0.0.1:${REG_PORT}/charts" --plain-http
echo "Pulling back"
rm -rf /tmp/vmcp-operator-oci-pull
mkdir -p /tmp/vmcp-operator-oci-pull
helm pull "oci://127.0.0.1:${REG_PORT}/charts/vmcp-operator" \
  --version 0.1.0 \
  --destination /tmp/vmcp-operator-oci-pull \
  --plain-http
ls -la /tmp/vmcp-operator-oci-pull
echo "LOCAL_OCI_OK chart=$(basename "$CHART_TGZ")"
