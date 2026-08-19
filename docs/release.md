# Release / image publish

Mirrors the [hewimetall/vmcp](https://github.com/hewimetall/vmcp) release workflow:

| Trigger | Effect |
| --- | --- |
| `git push` tag `v*` | Build `Dockerfile` target `runtime`, push to `ghcr.io/hewimetall/vmcp_operator`, attest |
| `workflow_dispatch` | Build only (no registry push) |

Workflow: [`.github/workflows/release.yml`](../.github/workflows/release.yml).

Cut a `v*` tag when a user-facing fix lands (CRD fields, crash fixes). Merges
to `main` do not publish an image. Installing the chart without that tag still
pulls the last release.

## Image and CRDs must move together

The image and `charts/vmcp-operator/crds/` are separate artifacts. Upgrading
only the operator Deployment leaves the old CRD schema in the cluster: the API
server **prunes** every new `spec` field with no warning, and the operator
quietly ignores the configuration. Apply the CRDs from the **same git tag** as
the image (see the Helm chart README).

## Health

`status.phase` is stored on the object and stays `Applied` even if the operator
is scaled to zero. Compare `metadata.generation` with `status.observedGeneration`.

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
