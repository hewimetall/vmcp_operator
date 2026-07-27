"""Detect immutable Gateway/MCP field mutations for Condition reporting."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ImmutableViolation:
    field: str
    old: str
    new: str

    @property
    def reason(self) -> str:
        return "ImmutableField"

    @property
    def message(self) -> str:
        return f"{self.field} is immutable ({self.old!r} → {self.new!r})"


GATEWAY_IMMUTABLE = (
    "persistence.storageClassName",
    "persistence.reclaimPolicy",
)

MCP_IMMUTABLE = (
    "gatewayRef.name",
)


def check_gateway_immutables(
    old_spec: dict[str, object],
    new_spec: dict[str, object],
) -> tuple[ImmutableViolation, ...]:
    violations: list[ImmutableViolation] = []
    old_p = old_spec.get("persistence") if isinstance(old_spec.get("persistence"), dict) else {}
    new_p = new_spec.get("persistence") if isinstance(new_spec.get("persistence"), dict) else {}
    assert isinstance(old_p, dict)
    assert isinstance(new_p, dict)
    for key, path in (
        ("storageClassName", "persistence.storageClassName"),
        ("reclaimPolicy", "persistence.reclaimPolicy"),
    ):
        old_v = old_p.get(key)
        new_v = new_p.get(key)
        if old_v is not None and new_v is not None and old_v != new_v:
            violations.append(
                ImmutableViolation(field=path, old=str(old_v), new=str(new_v))
            )
    # PVC size shrink is immutable; grow is allowed.
    old_size = old_p.get("size")
    new_size = new_p.get("size")
    if (
        isinstance(old_size, str)
        and isinstance(new_size, str)
        and old_size != new_size
        and _size_bytes(new_size) < _size_bytes(old_size)
    ):
        violations.append(
            ImmutableViolation(
                field="persistence.size",
                old=old_size,
                new=new_size,
            )
        )
    return tuple(violations)


def check_mcp_immutables(
    old_spec: dict[str, object],
    new_spec: dict[str, object],
) -> tuple[ImmutableViolation, ...]:
    old_ref = old_spec.get("gatewayRef") if isinstance(old_spec.get("gatewayRef"), dict) else {}
    new_ref = new_spec.get("gatewayRef") if isinstance(new_spec.get("gatewayRef"), dict) else {}
    assert isinstance(old_ref, dict)
    assert isinstance(new_ref, dict)
    old_name = old_ref.get("name")
    new_name = new_ref.get("name")
    if old_name is not None and new_name is not None and old_name != new_name:
        return (
            ImmutableViolation(
                field="gatewayRef.name",
                old=str(old_name),
                new=str(new_name),
            ),
        )
    return ()


def _size_bytes(raw: str) -> int:
    text = raw.strip().upper()
    units = {
        "KI": 1024,
        "MI": 1024**2,
        "GI": 1024**3,
        "TI": 1024**4,
        "K": 1000,
        "M": 1000**2,
        "G": 1000**3,
        "T": 1000**4,
    }
    for suffix, mult in units.items():
        if text.endswith(suffix):
            return int(float(text[: -len(suffix)]) * mult)
    return int(text)
