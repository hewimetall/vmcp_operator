from __future__ import annotations

import pytest

from vmcp_operator.adapters.driven.k8s.ssa import (
    ConflictError,
    InMemoryApplier,
    ServerSideApply,
)


@pytest.mark.asyncio
async def test_ssa_retries_conflict_with_force() -> None:
    applier = InMemoryApplier(conflicts_before_success=2)
    ssa = ServerSideApply(applier=applier, max_attempts=5)
    body = {"kind": "ConfigMap", "metadata": {"name": "x"}}
    out = await ssa.apply(body)
    assert out == body
    assert applier.applied is not None
    assert applier.applied[-1]["force"] is True
    assert len(applier.applied) == 1


@pytest.mark.asyncio
async def test_ssa_exhausts_retries() -> None:
    applier = InMemoryApplier(conflicts_before_success=10)
    ssa = ServerSideApply(applier=applier, max_attempts=3)
    with pytest.raises(ConflictError):
        await ssa.apply({"kind": "Service"})
