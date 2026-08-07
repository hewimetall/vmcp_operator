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


def _decode_secret_value(raw: object) -> str:
    if isinstance(raw, bytes):
        try:
            return base64.b64decode(raw).decode("utf-8")
        except Exception:
            return raw.decode("utf-8")
    text = str(raw)
    try:
        return base64.b64decode(text, validate=True).decode("utf-8")
    except Exception:
        return text


@dataclass(frozen=True, slots=True)
class Kr8sSecretValueLoader:
    async def get(self, namespace: str, ref: SecretRef) -> str | None:
        import kr8s
        from kr8s.asyncio.objects import Secret

        try:
            secret = await Secret.get(ref.name, namespace=namespace)
        except Exception:
            # Fallback for older/newer kr8s API shapes.
            try:
                api = await kr8s.asyncio.api()
                secret = None
                async for obj in api.get("secrets", namespace=namespace):
                    if obj.name == ref.name:
                        secret = obj
                        break
                if secret is None:
                    return None
            except Exception:
                return None

        data = getattr(secret, "data", None) or (secret.raw.get("data") or {})
        if ref.key not in data:
            return None
        return _decode_secret_value(data[ref.key])
