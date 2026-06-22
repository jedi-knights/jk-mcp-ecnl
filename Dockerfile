FROM python:3.13-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# Copy dependency files first for layer caching
COPY pyproject.toml .python-version uv.lock ./

# Install dependencies without the project itself so this layer is cached.
RUN uv sync --locked --no-install-project --no-dev

# Copy source
COPY src/ ./src/

# Install the project
RUN uv sync --locked --no-dev

# Expose default HTTP port (used when MCP_TRANSPORT=streamable-http).
# Ignored when running in stdio mode (the default).
EXPOSE 8000

# Default transport is stdio — the client launches the container with `docker run -i --rm`.
# Set MCP_TRANSPORT=streamable-http (and optionally HOST/PORT) to switch to HTTP mode.
CMD ["uv", "run", "--no-sync", "python", "-m", "ecnl.server"]
