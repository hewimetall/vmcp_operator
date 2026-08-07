"""Load Secret values via kr8s (live cluster) or an in-memory stub."""

from __future__ import annotations

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
        import base64

        import kr8s

        api = await kr8s.asyncio.api()
        try:
            secret = await api.get("secret", ref.name, namespace=namespace)
        except Exception:
            return None
        # Prefer decoded `.data` when kr8s exposes it; otherwise decode raw base64.
        decoded = getattr(secret, "data", None) or {}
        if ref.key in decoded:
            value = decoded[ref.key]
            return value.decode("utf-8") if isinstance(value, bytes) else str(value)
        raw = (secret.raw.get("data") or {}).get(ref.key)
        if raw is None:
            return None
        if isinstance(raw, bytes):
            return base64.b64decode(raw).decode("utf-8")
        return base64.b64decode(str(raw)).decode("utf-8")
