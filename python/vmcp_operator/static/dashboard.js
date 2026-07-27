/* global gridjs */
(() => {
  const gridHost = document.getElementById("environments-grid");
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

  loadEnvironments();
})();
