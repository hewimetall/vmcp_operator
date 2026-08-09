# Architecture delta — issue #4 (status / GC / edge)

Target architect-c4 workspace: [`ws-vmcp-operator`](https://architecture.runmcp.ru/view/ws-vmcp-operator)
(project `vmcp-operator`).

**Blocked in this Cloud Agent MCP proxy (2026-08-09):** every mutating tool
(`checkout_workspace`, `upsert_element`, `upsert_adr`, `upsert_board`) requires a
session with `branch_bound` + `kanban_bound`. `checkout_workspace` fails with
`takes 3 positional arguments but 4 were given`, so bind never completes and
live model writes cannot land from this agent. `validate_model(ws-vmcp-operator)`
still works (read path) and reports only pre-existing disconnected-element warnings.

The delta below is the **import checklist** for a local Cursor/desktop session
with a working architect-c4 checkout.

## New code atoms (under `driving_k8s` / `driven_k8s`)

| id | kind | parent | name | notes |
| --- | --- | --- | --- | --- |
| `code_status_patch` | code/function | `driving_k8s` | `apply_status` | Top-level CRD status via `patch.status` |
| `code_finalizer_patch` | code/function | `driving_k8s` | `schedule_finalizer_*` | Finalizers via `patch.fns` |
| `code_ownership` | code/function | `driving_k8s` | `attach_owner` | Controller `ownerReferences` |
| `code_gateway_toucher` | code/class | `driven_k8s` | `GatewayToucher` | Annotation wake `vmcp.io/mcp-generation` |

## Relationships (code↔code)

- `kopf_handlers` → `code_status_patch` — write phase/conditions after reconcile
- `kopf_handlers` → `code_finalizer_patch` — add/remove protection finalizers
- `uc_render_gateway_manifests` / Gateway reconcile → `code_ownership` → SSA apply
- `kopf_handlers` (MCP) → `code_gateway_toucher` → Gateway CR annotation

## ADR (proposed)

**Title:** Deliver CR status and finalizers outside Kopf result nesting  
**Status:** proposed  
**Context:** Kopf stores handler return values under `status.<handler_name>`; structural
CRD schemas prune unknown fields → empty PHASE, lost `addFinalizers`.  
**Decision:** Use `patch.status` for declared fields only; use `patch.fns` for
finalizer list ops; attach ownerRefs before SSA; wake parent Gateway on MCP change.  
**Consequences:** Printer columns work; GC and delete protection become real; hop
secret may still appear in admin HTTPRoute `set` filters (RBAC on HTTPRoute get).

## Render / CR knobs (update `uc_render_gateway_manifests` description)

- Public/admin identity header strip; admin hop inject
- `adminTokenSecretRef.writable` → `/state/tokens.json`
- `manage: false` BYO HTTPRoute; `extraFilters`; `spec.attachments` (TrafficPolicy)
