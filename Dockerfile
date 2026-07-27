# Operator runtime image. Built from uv python-build-standalone 3.15t.
# Official CPython Docker tags do not ship 3.15t yet; this Dockerfile uses uv.
FROM ghcr.io/astral-sh/uv:python3.15-bookworm-slim AS build

WORKDIR /src
COPY . .
RUN uv python install 3.15t \
 && uv sync --extra dev --no-dev \
 && uv run maturin build --release -o /wheels

FROM debian:bookworm-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/*
COPY --from=build /root/.local/share/uv/python /opt/python
# Placeholder: final free-threaded runtime wiring lands with image publish phase.
CMD ["true"]
