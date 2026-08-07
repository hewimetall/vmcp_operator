# Operator control plane (above vmcp)

Fleet features that live **in the operator**, not inside a single vmcp process.

| Surface | Path | SoT |
| --- | --- | --- |
| MCP add | `POST /api/gateways/{ns}/{gw}/mcps` | `VmcpMcpServer` CR |
| MCP get/list | `GET …/mcps` / `GET …/mcps/{name}` | CR watch/list |
| MCP update | `PUT …/mcps/{name}` | CR patch (SSA) |
| MCP remove | `DELETE …/mcps/{name}` | CR delete → reconcile GC |
| NL CRUD | `POST /api/nl` | same use cases |

This is intentionally different from `vmcp add/remove` (local `registry.json` on one host). The operator mutates **cluster desired state**; Kopf reconcile projects it into each Gateway’s artifacts.

## REST examples

```bash
# Add RemoteHttp MCP
curl -u admin:$PASS -X POST \
  https://operator.example/api/gateways/team-a/main/mcps \
  -H 'content-type: application/json' \
  -d '{"name":"docs","source":{"type":"RemoteHttp","url":"https://docs.example.com/mcp"},"forwardIdentity":false}'

# Update
curl -u admin:$PASS -X PUT \
  https://operator.example/api/gateways/team-a/main/mcps/docs \
  -H 'content-type: application/json' \
  -d '{"forwardIdentity":true,"url":"https://docs.example.com/v2/mcp"}'

# Remove
curl -u admin:$PASS -X DELETE \
  https://operator.example/api/gateways/team-a/main/mcps/docs
```

## NL CRUD

Deterministic RU/EN planner (no LLM). Also accepts structured JSON.

```bash
curl -u admin:$PASS -X POST https://operator.example/api/nl \
  -H 'content-type: application/json' \
  -d '{"utterance":"add mcp docs to team-a/main url https://docs.example.com/mcp"}'

curl -u admin:$PASS -X POST https://operator.example/api/nl \
  -H 'content-type: application/json' \
  -d '{"utterance":"удали mcp docs из team-a/main"}'

curl -u admin:$PASS -X POST https://operator.example/api/nl \
  -H 'content-type: application/json' \
  -d '{"utterance":"list mcps on team-a/main","dryRun":false}'

# Structured (agent-friendly)
curl -u admin:$PASS -X POST https://operator.example/api/nl \
  -H 'content-type: application/json' \
  -d '{"action":"update","gateway":"team-a/main","name":"docs","fields":{"enabled":false}}'
```

Supported utterances:

- `add|create|добавь mcp <name> to|в <ns>/<gw> url <url> [forward identity] [description …]`
- `add mcp <name> to <ns>/<gw> image <image>`
- `add|подключи mcp <name> to|к <ns>/<gw> via|через vmcp-proxy <peerNs>/<peerGw>`
- `remove|delete|удали mcp <name> from|из <ns>/<gw>`
- `update|обнови mcp <name> on|на <ns>/<gw> set forwardIdentity=true url=…`
- `list|список mcps on|для <ns>/<gw>`
- `get|покажи mcp <name> on|на <ns>/<gw>`

## Peer vmcp via `VmcpProxy`

One Gateway can mount another Gateway’s `[proxy]` surface (`/mcp-proxy` by default)
as an HTTP upstream — operator-level peering, not `vmcp add` inside a pod.

```yaml
source:
  type: VmcpProxy
  peerGatewayRef:
    name: code          # peer VmcpGateway
    namespace: team-a    # optional; defaults to consumer namespace
  path: /mcp-proxy      # must match peer spec.proxy.path
```

Resolved ClusterIP URL: `http://code.team-a.svc:8080/mcp-proxy`.

Requirements:

1. Peer `spec.proxy.enabled: true`
2. Consumer registers a `VmcpMcpServer` with `source.type: VmcpProxy`
3. Optional `bearerSecretRef` + `forwardIdentity: true` for authenticated/internal hops

Samples: `deploy/samples/mcp-vmcp-proxy.yaml`, `deploy/profiles/other/mcp-code-via-proxy.yaml`.

## Env

| Env | Default | Meaning |
| --- | --- | --- |
| `VMCP_OPERATOR_DASHBOARD_ENABLED` | off | Serve control-plane HTTP |
| `VMCP_OPERATOR_MCP_CATALOG` | `kr8s` | `kr8s` (live CRs) or `memory` (stub) |
