#!/usr/bin/env python3
"""Phase -1 spike: free-threaded Kopf watches two CR kinds concurrently."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread

import httpx
import kopf

assert sys._is_gil_enabled() is False, "GIL must stay disabled"

SEEN: dict[str, set[str]] = {"VmcpGateway": set(), "VmcpMcpServer": set()}
READY = asyncio.Event()
HTTP_OK = asyncio.Event()
START = time.monotonic()
SOAK_SECONDS = int(os.environ.get("VMCP_SPIKE_SOAK_SECONDS", "60"))
RESULT_PATH = Path(
    os.environ.get("VMCP_SPIKE_RESULT", "/tmp/phase-minus-one-result.json")
)


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        body = b'{"ok":true,"gil":false}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


def _kubectl(*args: str) -> None:
    subprocess.run(["kubectl", *args], check=True, capture_output=True, text=True)


def _apply_fixtures() -> None:
    _kubectl("create", "namespace", "team-a", "--dry-run=client", "-o", "yaml")
    subprocess.run(
        ["kubectl", "apply", "-f", "-"],
        check=True,
        text=True,
        capture_output=True,
        input="apiVersion: v1\nkind: Namespace\nmetadata:\n  name: team-a\n",
    )
    manifest = """
apiVersion: vmcp.io/v1alpha1
kind: VmcpGateway
metadata:
  name: main
  namespace: team-a
spec:
  image: registry.example.com/ai/vmcp:test
  adminTokenSecretRef:
    name: admin-tokens
  masterPasswordSecretRef:
    name: admin-pass
  publicRoute:
    hostname: main.example.com
    gatewayRef:
      name: kgateway
---
apiVersion: vmcp.io/v1alpha1
kind: VmcpMcpServer
metadata:
  name: docs
  namespace: team-a
spec:
  gatewayRef:
    name: main
  source:
    type: RemoteHttp
    url: https://docs.example.com/mcp
"""
    subprocess.run(
        ["kubectl", "apply", "-f", "-"],
        check=True,
        text=True,
        capture_output=True,
        input=manifest,
    )


@kopf.on.startup()
async def configure(settings: kopf.OperatorSettings, **_: object) -> None:
    settings.watching.server_timeout = 30
    settings.posting.enabled = False


@kopf.on.create("vmcp.io", "v1alpha1", "vmcpgateways")
@kopf.on.update("vmcp.io", "v1alpha1", "vmcpgateways")
async def on_gateway(name: str, **_: object) -> None:
    SEEN["VmcpGateway"].add(name)
    if SEEN["VmcpGateway"] and SEEN["VmcpMcpServer"]:
        READY.set()


@kopf.on.create("vmcp.io", "v1alpha1", "vmcpmcpservers")
@kopf.on.update("vmcp.io", "v1alpha1", "vmcpmcpservers")
async def on_mcp(name: str, **_: object) -> None:
    SEEN["VmcpMcpServer"].add(name)
    if SEEN["VmcpGateway"] and SEEN["VmcpMcpServer"]:
        READY.set()


async def _http_probe(port: int) -> None:
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"http://127.0.0.1:{port}/healthz", timeout=5.0)
        resp.raise_for_status()
        payload = resp.json()
        assert payload["ok"] is True
        assert sys._is_gil_enabled() is False
        HTTP_OK.set()


async def _orchestrate(port: int, stop: asyncio.Event) -> None:
    await asyncio.sleep(2)
    await asyncio.to_thread(_apply_fixtures)
    await asyncio.wait_for(READY.wait(), timeout=60)
    await _http_probe(port)
    end = time.monotonic() + SOAK_SECONDS
    mutations = 0
    while time.monotonic() < end:
        mutations += 1
        await asyncio.to_thread(_apply_fixtures)
        assert sys._is_gil_enabled() is False
        await asyncio.sleep(1)
    result = {
        "gil_enabled": sys._is_gil_enabled(),
        "gateways_seen": sorted(SEEN["VmcpGateway"]),
        "mcps_seen": sorted(SEEN["VmcpMcpServer"]),
        "http_ok": HTTP_OK.is_set(),
        "soak_seconds": SOAK_SECONDS,
        "mutations": mutations,
        "elapsed": round(time.monotonic() - START, 2),
        "cluster": "kwok",
    }
    RESULT_PATH.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2), flush=True)
    if result["gil_enabled"] or not result["http_ok"] or not result["gateways_seen"]:
        raise SystemExit(2)
    stop.set()


def main() -> None:
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    port = httpd.server_address[1]
    Thread(target=httpd.serve_forever, daemon=True).start()
    os.environ.setdefault("PYTHON_LAZY_IMPORTS", "normal")
    stop = asyncio.Event()

    async def _runner() -> None:
        task = asyncio.create_task(_orchestrate(port, stop))
        operator_task = asyncio.create_task(kopf.operator(clusterwide=True))
        await stop.wait()
        operator_task.cancel()
        try:
            await operator_task
        except asyncio.CancelledError:
            pass
        await task

    asyncio.run(_runner())


if __name__ == "__main__":
    main()
