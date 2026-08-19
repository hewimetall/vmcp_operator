"""Load Secret values via kr8s (live cluster) or an in-memory stub."""

from __future__ import annotations

import base64
from dataclasses import dataclass, field

from vmcp_operator.domain.models.gateway import SecretRef


@dataclass
class InMemorySecretValueLoader:
    values: dict[tuple[str, str, str], str] = field(default_factory=dict)

    async def get(self, namespace: str, ref: SecretRef) -> str | None:
        return self.values.get((namespace, ref.name, ref.key))


@dataclass(frozen=True, slots=True)
class Kr8sSecretValueLoader:
    async def get(self, namespace: str, ref: SecretRef) -> str | None:
        import kr8s
        from kr8s._exceptions import NotFoundError
        from kr8s.asyncio.objects import Secret

        api = await kr8s.asyncio.api()
        obj = Secret(
            {"metadata": {"name": ref.name, "namespace": namespace}},
            api=api,
        )
        try:
            if not await obj.exists():
                return None
            await obj.refresh()
        except NotFoundError:
            return None
        except Exception:
            return None
        raw = (obj.raw.get("data") or {}).get(ref.key)
        if raw is None:
            return None
        return _decode_secret_value(raw)


def _decode_secret_value(raw: object) -> str | None:
    if isinstance(raw, bytes):
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return base64.b64decode(raw).decode("utf-8")
    text = str(raw)
    try:
        return base64.b64decode(text, validate=True).decode("utf-8")
    except Exception:
        return text


__all__ = ["InMemorySecretValueLoader", "Kr8sSecretValueLoader"]
