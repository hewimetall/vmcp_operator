"""httpx client for a Gateway vmcp ClusterIP /api/v1 surface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


class VmcpApiError(RuntimeError):
    """Upstream vmcp API returned an unexpected response."""


@dataclass(frozen=True, slots=True)
class ReloadStatus:
    desired_sha256: str
    observed_sha256: str | None
    matched: bool
    upstream_names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class VmcpApiClient:
    """Talk to one Gateway's internal /api/v1 (never publicly exposed)."""

    base_url: str
    admin_token: str
    timeout: float = 10.0

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.admin_token}",
            "Accept": "application/json",
        }

    async def reload_registry(self, *, desired_sha256: str) -> ReloadStatus:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
            resp = await client.post("/api/v1/registry/reload", headers=self._headers())
            if resp.status_code >= 400:
                raise VmcpApiError(f"reload failed: HTTP {resp.status_code}")
            payload = resp.json()
        observed = payload.get("sha256") or payload.get("registrySha256")
        names = tuple(sorted(str(n) for n in payload.get("upstreams", [])))
        return ReloadStatus(
            desired_sha256=desired_sha256,
            observed_sha256=str(observed) if observed is not None else None,
            matched=observed == desired_sha256,
            upstream_names=names,
        )

    async def list_upstream_names(self) -> tuple[str, ...]:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
            resp = await client.get("/api/v1/upstreams", headers=self._headers())
            if resp.status_code >= 400:
                raise VmcpApiError(f"list upstreams failed: HTTP {resp.status_code}")
            payload = resp.json()
        if isinstance(payload, list):
            return tuple(sorted(str(item.get("name", item)) for item in payload))
        return tuple(sorted(str(n) for n in payload.get("upstreams", [])))

    async def issue_static_token(self, *, client_name: str, scope: str = "mcp:use") -> str:
        body: dict[str, Any] = {"name": client_name, "scopes": [scope]}
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
            resp = await client.post(
                "/api/v1/tokens",
                headers=self._headers(),
                json=body,
            )
            if resp.status_code == 409:
                raise FileExistsError(f"token `{client_name}` already exists")
            if resp.status_code >= 400:
                raise VmcpApiError(f"issue token failed: HTTP {resp.status_code}")
            payload = resp.json()
        token = payload.get("token")
        if not token:
            raise VmcpApiError("issue token response missing token")
        return str(token)
