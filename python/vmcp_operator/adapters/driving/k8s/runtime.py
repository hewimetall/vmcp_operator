"""Injectable operator runtime for Kopf handlers and tests."""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from vmcp_operator.adapters.driven.k8s.ssa import InMemoryApplier, ServerSideApply
from vmcp_operator.adapters.driven.registry.engine import RegistryEngine
from vmcp_operator.adapters.driving.k8s.reconcile import GatewayReconcile, McpReconcile
from vmcp_operator.domain.models.artifacts import SkillDesired
from vmcp_operator.domain.models.gateway import GatewayDesired, GatewayKey
from vmcp_operator.domain.models.mcp import McpServerDesired
from vmcp_operator.domain.usecases.reconcile_artifacts import ReconcileGatewayArtifacts
from vmcp_operator.domain.usecases.render_gateway_manifests import RenderGatewayManifests
from vmcp_operator.domain.usecases.render_mcp_manifests import RenderMcpManifests


@dataclass
class EmptySkillLoader:
    async def load_skills(
        self,
        gateway: GatewayDesired,
        mcps: list[McpServerDesired],
    ) -> list[SkillDesired]:
        del gateway, mcps
        return []


ListMcps = Callable[[GatewayKey], Awaitable[list[McpServerDesired]]]
GetGateway = Callable[[GatewayKey], Awaitable[GatewayDesired | None]]
UnregisterFn = Callable[[GatewayKey, str], Awaitable[bool]]


@dataclass
class OperatorRuntime:
    gateway_reconcile: GatewayReconcile
    mcp_reconcile: McpReconcile
    list_mcps: ListMcps
    get_gateway: GetGateway
    unregister_upstream: UnregisterFn | None = None
    pending: set[str] = field(default_factory=set)

    def enqueue(self, key: GatewayKey) -> None:
        self.pending.add(key.as_str())

    @classmethod
    def in_memory(
        cls,
        *,
        gateways: dict[str, GatewayDesired] | None = None,
        mcps: dict[str, list[McpServerDesired]] | None = None,
        skill_loader: Any | None = None,
        secrets: Any | None = None,
    ) -> OperatorRuntime:
        store_g = gateways or {}
        store_m = mcps or {}
        applier = InMemoryApplier()
        apply = ServerSideApply(applier=applier)
        artifacts = ReconcileGatewayArtifacts(
            renderer=RegistryEngine(),
            skill_loader=skill_loader or EmptySkillLoader(),
        )
        gateway_reconcile = GatewayReconcile(
            artifacts=artifacts,
            manifests=RenderGatewayManifests(),
            apply=apply,
            secrets=secrets,
        )
        mcp_reconcile = McpReconcile(
            manifests=RenderMcpManifests(),
            apply=apply,
        )

        async def _list(key: GatewayKey) -> list[McpServerDesired]:
            return list(store_m.get(key.as_str(), []))

        async def _get(key: GatewayKey) -> GatewayDesired | None:
            return store_g.get(key.as_str())

        runtime = cls(
            gateway_reconcile=gateway_reconcile,
            mcp_reconcile=mcp_reconcile,
            list_mcps=_list,
            get_gateway=_get,
        )
        runtime.applier = applier  # type: ignore[attr-defined]
        return runtime

    @classmethod
    def for_cluster(cls, *, skill_loader: Any | None = None) -> OperatorRuntime:
        """Live Kubernetes apply + CR catalogs + Secret hop materialization."""
        from vmcp_operator.adapters.driven.k8s.gateway_catalog import Kr8sGatewayRepository
        from vmcp_operator.adapters.driven.k8s.kr8s_applier import Kr8sServerSideApplier
        from vmcp_operator.adapters.driven.k8s.mcp_catalog import Kr8sMcpCatalog
        from vmcp_operator.adapters.driven.k8s.secret_loader import Kr8sSecretValueLoader

        apply = ServerSideApply(
            applier=Kr8sServerSideApplier(),
            field_manager="vmcp-operator",
        )
        artifacts = ReconcileGatewayArtifacts(
            renderer=RegistryEngine(),
            skill_loader=skill_loader or EmptySkillLoader(),
        )
        catalog = Kr8sMcpCatalog()
        gateways = Kr8sGatewayRepository()

        async def _list(key: GatewayKey) -> list[McpServerDesired]:
            return await catalog.list_for_gateway(key)

        async def _get(key: GatewayKey) -> GatewayDesired | None:
            return await gateways.get(key)

        return cls(
            gateway_reconcile=GatewayReconcile(
                artifacts=artifacts,
                manifests=RenderGatewayManifests(),
                apply=apply,
                secrets=Kr8sSecretValueLoader(),
            ),
            mcp_reconcile=McpReconcile(
                manifests=RenderMcpManifests(),
                apply=apply,
            ),
            list_mcps=_list,
            get_gateway=_get,
        )


_RUNTIME: OperatorRuntime | None = None


def get_runtime() -> OperatorRuntime:
    global _RUNTIME
    if _RUNTIME is None:
        mode = os.environ.get("VMCP_OPERATOR_RUNTIME", "").lower()
        if mode in {"memory", "inmemory", "stub"}:
            _RUNTIME = OperatorRuntime.in_memory()
        elif mode in {"kr8s", "cluster"} or bool(os.environ.get("KUBECONFIG")):
            _RUNTIME = OperatorRuntime.for_cluster()
        else:
            # Unit tests / local without kubeconfig stay in-memory.
            _RUNTIME = OperatorRuntime.in_memory()
    return _RUNTIME


def set_runtime(runtime: OperatorRuntime | None) -> None:
    global _RUNTIME
    _RUNTIME = runtime
