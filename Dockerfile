# syntax=docker/dockerfile:1.7
#
# Multi-stage build for vmcp-operator (free-threaded CPython 3.15t + PyO3).
# Release shape mirrors hewimetall/vmcp (Dockerfile target `runtime` → GHCR).
#
# Official CPython Docker tags do not ship 3.15t; install via uv standalone.
#   docker build --target runtime -t ghcr.io/hewimetall/vmcp_operator:local .
#

FROM debian:bookworm-slim AS build

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        git \
        libssl-dev \
        pkg-config \
 && rm -rf /var/lib/apt/lists/*

# edition = "2024" / rust-version = "1.89"
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
    | sh -s -- -y --profile minimal --default-toolchain stable \
 && . "$HOME/.cargo/env" \
 && rustc --version
ENV PATH=/root/.cargo/bin:$PATH

ENV UV_PYTHON_INSTALL_DIR=/opt/python \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /src
COPY . .

RUN uv python install 3.15t \
 && uv venv --python 3.15t /opt/venv \
 && uv sync --frozen --no-dev --no-install-project \
 && uv pip install maturin \
 && uv run --no-sync maturin build --release -o /wheels \
 && uv pip install /wheels/vmcp_operator*.whl \
 && uv pip uninstall -y maturin \
 && /opt/venv/bin/python -c 'import sys; assert not sys._is_gil_enabled(), "GIL enabled"'

# ------------------------------------------------------------------
# Runtime image — ENTRYPOINT is the console script (not CMD true).
# ------------------------------------------------------------------
FROM debian:bookworm-slim AS runtime

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        ca-certificates \
        libgcc-s1 \
        libstdc++6 \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --system --uid 65532 --home-dir /home/nonroot --create-home nonroot

COPY --from=build /opt/python /opt/python
COPY --from=build /opt/venv /opt/venv

ENV PATH=/opt/venv/bin:$PATH \
    UV_PYTHON_INSTALL_DIR=/opt/python \
    PYTHON_LAZY_IMPORTS=normal \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

USER 65532:65532
WORKDIR /home/nonroot
ENTRYPOINT ["vmcp-operator"]
