"""Wire operator control-plane use cases for the dashboard."""

from __future__ import annotations

from dataclasses import dataclass

from vmcp_operator.domain.ports import GatewayRepository, McpCatalog
from vmcp_operator.domain.usecases.manage_mcp import (
    AddMcp,
    GetMcp,
    ListMcps,
    RemoveMcp,
    UpdateMcp,
)
from vmcp_operator.domain.usecases.nl_crud import NlCrud


@dataclass(frozen=True, slots=True)
class ControlPlane:
    list_mcps: ListMcps
    get_mcp: GetMcp
    add_mcp: AddMcp
    update_mcp: UpdateMcp
    remove_mcp: RemoveMcp
    nl_crud: NlCrud


def build_control_plane(
    *,
    gateways: GatewayRepository,
    catalog: McpCatalog,
) -> ControlPlane:
    list_mcps = ListMcps(catalog=catalog, gateways=gateways)
    get_mcp = GetMcp(catalog=catalog, gateways=gateways)
    add_mcp = AddMcp(catalog=catalog, gateways=gateways)
    update_mcp = UpdateMcp(catalog=catalog, gateways=gateways)
    remove_mcp = RemoveMcp(catalog=catalog, gateways=gateways)
    return ControlPlane(
        list_mcps=list_mcps,
        get_mcp=get_mcp,
        add_mcp=add_mcp,
        update_mcp=update_mcp,
        remove_mcp=remove_mcp,
        nl_crud=NlCrud(
            add_mcp=add_mcp,
            update_mcp=update_mcp,
            remove_mcp=remove_mcp,
            list_mcps=list_mcps,
            get_mcp=get_mcp,
        ),
    )
