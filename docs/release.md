# Release / image publish

Mirrors the [hewimetall/vmcp](https://github.com/hewimetall/vmcp) release workflow:

| Trigger | Effect |
| --- | --- |
| `git push` tag `v*` | Build `Dockerfile` target `runtime`, push to `ghcr.io/hewimetall/vmcp_operator`, attest |
| `workflow_dispatch` | Build only (no registry push) |

Workflow: [`.github/workflows/release.yml`](../.github/workflows/release.yml).

## Tags

`docker/metadata-action` produces:

- `{{version}}` (e.g. `0.1.0` from tag `v0.1.0`)
- `{{major}}.{{minor}}`
- `latest` (tag pushes only)
- `sha-<short>`

## Local / CI smoke

```bash
docker build --target runtime -t vmcp-operator:local .
docker image inspect vmcp-operator:local --format '{{.Config.Entrypoint}}'
# → ["vmcp-operator"]
```

CI job `docker` builds the same target without pushing.
