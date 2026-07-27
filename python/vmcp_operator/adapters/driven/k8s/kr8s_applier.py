"""kr8s-backed server-side apply for KWOK/real clusters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import kr8s
from kr8s.asyncio.objects import APIObject, new_class

from vmcp_operator.adapters.driven.k8s.ssa import ConflictError


@dataclass
class Kr8sServerSideApplier:
    """Apply arbitrary API objects via SSA patch semantics."""

    api: Any | None = None

    async def _api(self) -> Any:
        if self.api is None:
            self.api = await kr8s.asyncio.api()
        return self.api

    async def server_side_apply(
        self,
        body: dict[str, Any],
        *,
        field_manager: str,
        force: bool,
    ) -> dict[str, Any]:
        api = await self._api()
        api_version = str(body.get("apiVersion", "v1"))
        kind = str(body["kind"])
        metadata = body.get("metadata") or {}
        if "name" not in metadata:
            raise ValueError("resource metadata.name is required")
        namespace = metadata.get("namespace")

        group, _, version = api_version.partition("/")
        if not version:
            version = group
            group = ""
        plural = _guess_plural(kind)
        cls = new_class(
            kind=kind,
            plural=plural,
            group=group,
            version=version,
            namespaced=namespace is not None,
            asyncio=True,
        )
        obj: APIObject = cls(body, api=api)
        try:
            # Prefer create when absent; fall back to patch/replace style apply.
            exists = await obj.exists()
            if not exists:
                await obj.create()
                return dict(obj.raw)
            await obj.patch(
                body,
                type="apply",
                field_manager=field_manager,
                force=force,
            )
            await obj.refresh()
            return dict(obj.raw)
        except Exception as exc:
            message = str(exc).lower()
            if "conflict" in message or "429" in message:
                raise ConflictError(str(exc)) from exc
            # Some KWOK/mock paths lack apply patch; replace as best-effort.
            try:
                await obj.patch(body)
                await obj.refresh()
                return dict(obj.raw)
            except Exception as inner:
                if "conflict" in str(inner).lower():
                    raise ConflictError(str(inner)) from inner
                raise


def _guess_plural(kind: str) -> str:
    lower = kind.lower()
    if lower.endswith("s"):
        return lower + "es"
    if lower.endswith("y"):
        return lower[:-1] + "ies"
    return lower + "s"
