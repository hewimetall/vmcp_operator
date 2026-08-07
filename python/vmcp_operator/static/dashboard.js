/* global gridjs */
(() => {
  const gridHost = document.getElementById("environments-grid");
  const controlHost = document.getElementById("control-plane");
  if (!gridHost || typeof gridjs === "undefined") {
    return;
  }

  const status = document.createElement("p");
  status.className = "text-secondary";
  status.textContent = "Loading environments…";
  gridHost.parentElement.insertBefore(status, gridHost);

  const tokenBox = document.createElement("div");
  tokenBox.className = "card mt-3";
  tokenBox.innerHTML = `
    <div class="card-body">
      <h3 class="card-title">Issue mcp:use token</h3>
      <div class="row g-2">
        <div class="col-md-5">
          <input id="token-gateway" class="form-control" placeholder="namespace/gateway" />
        </div>
        <div class="col-md-5">
          <input id="token-client" class="form-control" placeholder="client name" />
        </div>
        <div class="col-md-2">
          <button id="token-submit" class="btn btn-primary w-100" type="button">Issue</button>
        </div>
      </div>
      <pre id="token-once" class="mt-3 d-none"></pre>
    </div>`;
  gridHost.parentElement.appendChild(tokenBox);

  if (controlHost) {
    controlHost.innerHTML = `
      <div class="card">
        <div class="card-body">
          <h3 class="card-title">MCP catalog (operator control plane)</h3>
          <p class="text-secondary">
            Mutates <code>VmcpMcpServer</code> CRs — not the per-instance vmcp CLI.
          </p>
          <div class="row g-2 align-items-end">
            <div class="col-md-4">
              <label class="form-label" for="mcp-gateway">Gateway</label>
              <input id="mcp-gateway" class="form-control" placeholder="team-a/main" />
            </div>
            <div class="col-md-3">
              <label class="form-label" for="mcp-name">Name</label>
              <input id="mcp-name" class="form-control" placeholder="docs" />
            </div>
            <div class="col-md-5">
              <label class="form-label" for="mcp-url">Remote HTTP URL</label>
              <input id="mcp-url" class="form-control" placeholder="https://docs.example.com/mcp" />
            </div>
            <div class="col-md-3">
              <div class="form-check mt-3">
                <input id="mcp-forward" class="form-check-input" type="checkbox" />
                <label class="form-check-label" for="mcp-forward">forwardIdentity</label>
              </div>
            </div>
            <div class="col-md-9">
              <div class="btn-list">
                <button id="mcp-list" class="btn" type="button">List</button>
                <button id="mcp-add" class="btn btn-primary" type="button">Add</button>
                <button id="mcp-update" class="btn" type="button">Update</button>
                <button id="mcp-remove" class="btn btn-outline-danger" type="button">Remove</button>
              </div>
            </div>
          </div>
          <pre id="mcp-out" class="mt-3"></pre>
        </div>
      </div>
      <div class="card mt-3">
        <div class="card-body">
          <h3 class="card-title">NL CRUD</h3>
          <p class="text-secondary mb-2">
            Examples:
            <code>add mcp docs to team-a/main url https://docs.example.com/mcp</code>
            ·
            <code>подключи mcp code-peer к team-a/main через vmcp-proxy team-a/code</code>
            ·
            <code>удали mcp docs из team-a/main</code>
            ·
            <code>list mcps on team-a/main</code>
          </p>
          <div class="row g-2">
            <div class="col-md-9">
              <input id="nl-text" class="form-control" placeholder="NL utterance" />
            </div>
            <div class="col-md-2">
              <div class="form-check mt-2">
                <input id="nl-dry" class="form-check-input" type="checkbox" />
                <label class="form-check-label" for="nl-dry">dry-run</label>
              </div>
            </div>
            <div class="col-md-1">
              <button id="nl-run" class="btn btn-primary w-100" type="button">Run</button>
            </div>
          </div>
          <pre id="nl-out" class="mt-3"></pre>
        </div>
      </div>`;
  }

  function gatewayParts(raw) {
    const value = raw.trim();
    const idx = value.indexOf("/");
    if (idx <= 0 || idx === value.length - 1) {
      return null;
    }
    return { ns: value.slice(0, idx), name: value.slice(idx + 1), key: value };
  }

  async function loadEnvironments() {
    const resp = await fetch("/api/environments", { credentials: "same-origin" });
    if (!resp.ok) {
      status.textContent = `Failed to load environments (${resp.status})`;
      return;
    }
    const rows = await resp.json();
    status.textContent = `${rows.length} environment(s)`;
    // eslint-disable-next-line no-new
    new gridjs.Grid({
      columns: ["Gateway", "Phase", "Public host", "Admin"],
      data: rows.map((row) => [
        row.key,
        row.phase,
        row.publicHostname,
        row.adminUrl
          ? gridjs.html(`<a href="${row.adminUrl}" rel="noopener">admin</a>`)
          : "—",
      ]),
      search: true,
      sort: true,
      pagination: { enabled: true, limit: 10 },
    }).render(gridHost);
  }

  document.getElementById("token-submit").addEventListener("click", async () => {
    const gateway = document.getElementById("token-gateway").value.trim();
    const clientName = document.getElementById("token-client").value.trim();
    const once = document.getElementById("token-once");
    once.classList.add("d-none");
    const resp = await fetch("/api/tokens", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ gateway, clientName }),
    });
    const payload = await resp.json();
    if (!resp.ok) {
      once.textContent = `Error: ${payload.error || resp.status}`;
      once.classList.remove("d-none");
      return;
    }
    once.textContent = `scope=${payload.scope}\ntoken=${payload.token}\n(shown once; not stored)`;
    once.classList.remove("d-none");
  });

  if (controlHost) {
    const mcpOut = document.getElementById("mcp-out");
    const nlOut = document.getElementById("nl-out");

    async function mcpRequest(method, path, body) {
      const resp = await fetch(path, {
        method,
        credentials: "same-origin",
        headers: body ? { "Content-Type": "application/json" } : undefined,
        body: body ? JSON.stringify(body) : undefined,
      });
      const payload = await resp.json();
      mcpOut.textContent = JSON.stringify({ status: resp.status, ...payload }, null, 2);
      return resp;
    }

    document.getElementById("mcp-list").addEventListener("click", async () => {
      const gw = gatewayParts(document.getElementById("mcp-gateway").value);
      if (!gw) {
        mcpOut.textContent = "Error: gateway must be namespace/name";
        return;
      }
      await mcpRequest("GET", `/api/gateways/${gw.ns}/${gw.name}/mcps`);
    });

    document.getElementById("mcp-add").addEventListener("click", async () => {
      const gw = gatewayParts(document.getElementById("mcp-gateway").value);
      const name = document.getElementById("mcp-name").value.trim();
      const url = document.getElementById("mcp-url").value.trim();
      if (!gw || !name || !url) {
        mcpOut.textContent = "Error: gateway, name, and url are required";
        return;
      }
      await mcpRequest("POST", `/api/gateways/${gw.ns}/${gw.name}/mcps`, {
        name,
        source: { type: "RemoteHttp", url },
        forwardIdentity: document.getElementById("mcp-forward").checked,
      });
    });

    document.getElementById("mcp-update").addEventListener("click", async () => {
      const gw = gatewayParts(document.getElementById("mcp-gateway").value);
      const name = document.getElementById("mcp-name").value.trim();
      const url = document.getElementById("mcp-url").value.trim();
      if (!gw || !name) {
        mcpOut.textContent = "Error: gateway and name are required";
        return;
      }
      const fields = {
        forwardIdentity: document.getElementById("mcp-forward").checked,
      };
      if (url) {
        fields.url = url;
      }
      await mcpRequest("PUT", `/api/gateways/${gw.ns}/${gw.name}/mcps/${name}`, fields);
    });

    document.getElementById("mcp-remove").addEventListener("click", async () => {
      const gw = gatewayParts(document.getElementById("mcp-gateway").value);
      const name = document.getElementById("mcp-name").value.trim();
      if (!gw || !name) {
        mcpOut.textContent = "Error: gateway and name are required";
        return;
      }
      await mcpRequest("DELETE", `/api/gateways/${gw.ns}/${gw.name}/mcps/${name}`);
    });

    document.getElementById("nl-run").addEventListener("click", async () => {
      const utterance = document.getElementById("nl-text").value.trim();
      const dryRun = document.getElementById("nl-dry").checked;
      const resp = await fetch("/api/nl", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ utterance, dryRun }),
      });
      const payload = await resp.json();
      nlOut.textContent = JSON.stringify({ status: resp.status, ...payload }, null, 2);
    });
  }

  loadEnvironments();
})();
