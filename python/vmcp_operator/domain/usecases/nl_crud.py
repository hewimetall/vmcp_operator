"""Natural-language CRUD planner/executor for the operator control plane.

Deterministic RU/EN patterns — no LLM dependency. Structured JSON intents are
also accepted so agents can skip the text parser.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from vmcp_operator.domain.models.control_plane import McpMutation, NlCrudResult, NlIntent
from vmcp_operator.domain.models.gateway import GatewayKey
from vmcp_operator.domain.usecases.manage_mcp import (
    AddMcp,
    GetMcp,
    ListMcps,
    McpConflictError,
    McpNotFoundError,
    RemoveMcp,
    UpdateMcp,
    mcp_from_add_body,
)

_GATEWAY = r"(?P<gateway>[\w.-]+/[\w.-]+)"
_PEER = r"(?P<peer>[\w.-]+/[\w.-]+)"
_NAME = r"(?P<name>[\w-]+)"

# Cyrillic keywords are intentional (RU NL surface).
_ADD_PROXY = re.compile(
    rf"^(?:add|create|attach|добавь|добавить|создай|создать|подключи|подключить)\s+mcp\s+"
    rf"{_NAME}\s+(?:to|on|in|в|на|к)\s+{_GATEWAY}\s+"
    rf"(?:via\s+|через\s+)?vmcp-proxy\s+{_PEER}"
    rf"(?:\s+forward[_ ]?identity(?:=(?P<fi>true|false|да|нет))?)?"
    rf"(?:\s+(?P<desc_kw>desc|description|описание)\s+(?P<description>.+))?$",
    re.IGNORECASE,
)
_ADD = re.compile(
    rf"^(?:add|create|добавь|добавить|создай|создать)\s+mcp\s+{_NAME}\s+"
    rf"(?:to|on|в|на)\s+{_GATEWAY}\s+"
    rf"(?:(?P<url_kw>url|с\s+url)\s+(?P<url>\S+)|(?P<img_kw>image|образ)\s+(?P<image>\S+))"  # noqa: RUF001
    rf"(?:\s+forward[_ ]?identity(?:=(?P<fi>true|false|да|нет))?)?"
    rf"(?:\s+(?P<desc_kw>desc|description|описание)\s+(?P<description>.+))?$",
    re.IGNORECASE,
)
_REMOVE = re.compile(
    rf"^(?:remove|delete|удали|удалить)\s+mcp\s+{_NAME}\s+"
    rf"(?:from|on|из)\s+{_GATEWAY}$",
    re.IGNORECASE,
)
_UPDATE = re.compile(
    rf"^(?:update|patch|обнови|обновить)\s+mcp\s+{_NAME}\s+"
    rf"(?:on|in|на|в)\s+{_GATEWAY}\s+"
    rf"(?:set\s+)?(?P<field_blob>.+)$",
    re.IGNORECASE,
)
_LIST = re.compile(
    rf"^(?:list|show|список|покажи|перечисли)\s+mcps?\s+"
    rf"(?:on|in|for|для|на|в)\s+{_GATEWAY}$",
    re.IGNORECASE,
)
_GET = re.compile(
    rf"^(?:get|show|покажи)\s+mcp\s+{_NAME}\s+"
    rf"(?:on|in|на|в)\s+{_GATEWAY}$",
    re.IGNORECASE,
)
_FIELD = re.compile(
    r"(?P<key>forwardIdentity|enabled|url|image|description)\s*=\s*"
    r"(?P<val>\"[^\"]*\"|'[^']*'|true|false|да|нет|\S+)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class NlCrud:
    add_mcp: AddMcp
    update_mcp: UpdateMcp
    remove_mcp: RemoveMcp
    list_mcps: ListMcps
    get_mcp: GetMcp

    def parse(self, utterance: str, *, dry_run: bool = False) -> NlIntent:
        text = " ".join(utterance.strip().split())
        if not text:
            raise ValueError("utterance must be non-empty")

        if m := _ADD_PROXY.match(text):
            fields = {
                "source": {
                    "type": "VmcpProxy",
                    "peerGatewayRef": {
                        "namespace": m.group("peer").split("/", 1)[0],
                        "name": m.group("peer").split("/", 1)[1],
                    },
                }
            }
            if m.group("fi") is not None:
                fields["forwardIdentity"] = _as_bool(m.group("fi"))
            elif "forward" in text.lower() and "identity" in text.lower():
                fields["forwardIdentity"] = True
            if m.group("description"):
                fields["description"] = m.group("description").strip()
            return NlIntent(
                mutation=McpMutation.ADD,
                gateway=_gateway(m.group("gateway")),
                name=m.group("name"),
                fields=fields,
                dry_run=dry_run,
            )

        if m := _ADD.match(text):
            fields = {}
            if m.group("url"):
                fields["source"] = {"type": "RemoteHttp", "url": m.group("url")}
            else:
                fields["source"] = {"type": "ContainerImage", "image": m.group("image")}
            if m.group("fi") is not None:
                fields["forwardIdentity"] = _as_bool(m.group("fi"))
            elif "forward" in text.lower() and "identity" in text.lower():
                fields["forwardIdentity"] = True
            if m.group("description"):
                fields["description"] = m.group("description").strip()
            return NlIntent(
                mutation=McpMutation.ADD,
                gateway=_gateway(m.group("gateway")),
                name=m.group("name"),
                fields=fields,
                dry_run=dry_run,
            )

        if m := _REMOVE.match(text):
            return NlIntent(
                mutation=McpMutation.REMOVE,
                gateway=_gateway(m.group("gateway")),
                name=m.group("name"),
                dry_run=dry_run,
            )

        if m := _UPDATE.match(text):
            fields = _parse_fields(m.group("field_blob"))
            return NlIntent(
                mutation=McpMutation.UPDATE,
                gateway=_gateway(m.group("gateway")),
                name=m.group("name"),
                fields=fields,
                dry_run=dry_run,
            )

        if m := _LIST.match(text):
            return NlIntent(
                mutation=McpMutation.LIST,
                gateway=_gateway(m.group("gateway")),
                dry_run=dry_run,
            )

        if m := _GET.match(text):
            return NlIntent(
                mutation=McpMutation.GET,
                gateway=_gateway(m.group("gateway")),
                name=m.group("name"),
                dry_run=dry_run,
            )

        raise ValueError(
            "unrecognized NL CRUD utterance; expected add/remove/update/list/get mcp "
            "(or add … via vmcp-proxy …)"
        )

    def intent_from_structured(self, body: dict[str, Any]) -> NlIntent:
        mutation = McpMutation(str(body.get("action") or body.get("mutation") or ""))
        gateway_raw = body.get("gateway")
        gateway = _gateway(str(gateway_raw)) if gateway_raw else None
        return NlIntent(
            mutation=mutation,
            gateway=gateway,
            name=body.get("name"),
            fields=body.get("fields") if isinstance(body.get("fields"), dict) else body.get("spec"),
            dry_run=bool(body.get("dryRun", False)),
        )

    async def execute(self, intent: NlIntent) -> NlCrudResult:
        if intent.gateway is None:
            raise ValueError("gateway is required")
        needs_name = intent.mutation in {
            McpMutation.ADD,
            McpMutation.UPDATE,
            McpMutation.REMOVE,
            McpMutation.GET,
        }
        if needs_name and not intent.name:
            raise ValueError("name is required")

        if intent.dry_run:
            return NlCrudResult(
                intent=intent,
                applied=False,
                message=f"dry-run {intent.mutation.value}",
            )

        try:
            return await self._apply(intent)
        except McpConflictError as exc:
            raise ValueError(str(exc)) from exc
        except McpNotFoundError as exc:
            raise LookupError(str(exc)) from exc

    async def _apply(self, intent: NlIntent) -> NlCrudResult:
        assert intent.gateway is not None
        if intent.mutation == McpMutation.LIST:
            rows = await self.list_mcps.execute(intent.gateway)
            return NlCrudResult(
                intent=intent,
                applied=True,
                message=f"{len(rows)} mcp(s)",
                mcps=tuple(rows),
            )
        if intent.mutation == McpMutation.GET:
            assert intent.name is not None
            mcp = await self.get_mcp.execute(intent.gateway, intent.name)
            return NlCrudResult(
                intent=intent,
                applied=True,
                message="ok",
                mcp=mcp,
            )
        if intent.mutation == McpMutation.ADD:
            assert intent.name is not None
            mcp = mcp_from_add_body(intent.gateway, intent.name, intent.fields or {})
            result = await self.add_mcp.execute(mcp)
            return NlCrudResult(
                intent=intent,
                applied=True,
                message="added",
                mcp=result.mcp,
            )
        if intent.mutation == McpMutation.UPDATE:
            assert intent.name is not None
            result = await self.update_mcp.execute(
                intent.gateway,
                intent.name,
                fields=intent.fields or {},
            )
            return NlCrudResult(
                intent=intent,
                applied=True,
                message="updated",
                mcp=result.mcp,
            )
        if intent.mutation == McpMutation.REMOVE:
            assert intent.name is not None
            result = await self.remove_mcp.execute(intent.gateway, intent.name)
            return NlCrudResult(
                intent=intent,
                applied=True,
                message="removed",
                mcp=result.mcp,
            )
        raise ValueError(f"unsupported mutation {intent.mutation}")  # pragma: no cover


def _gateway(raw: str) -> GatewayKey:
    if "/" not in raw:
        raise ValueError("gateway must be namespace/name")
    ns, name = raw.split("/", 1)
    if not ns or not name:
        raise ValueError("gateway must be namespace/name")
    return GatewayKey(namespace=ns, name=name)


def _parse_fields(blob: str) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for match in _FIELD.finditer(blob):
        key = match.group("key")
        # Normalize camelCase from regex alternatives.
        if key.lower() == "forwardidentity":
            key = "forwardIdentity"
        elif key.lower() == "enabled":
            key = "enabled"
        elif key.lower() == "url":
            key = "url"
        elif key.lower() == "image":
            key = "image"
        elif key.lower() == "description":
            key = "description"
        val = match.group("val")
        if (val.startswith('"') and val.endswith('"')) or (
            val.startswith("'") and val.endswith("'")
        ):
            val = val[1:-1]
        if key in {"forwardIdentity", "enabled"}:
            fields[key] = _as_bool(val)
        else:
            fields[key] = val
    if not fields:
        raise ValueError("update fields must look like key=value pairs")
    return fields


def _as_bool(raw: str) -> bool:
    value = raw.strip().lower()
    if value in {"true", "1", "yes", "да", "on"}:
        return True
    if value in {"false", "0", "no", "нет", "off"}:
        return False
    raise ValueError(f"invalid boolean `{raw}`")
