# Quickstart

## Install

```bash
uv sync
```

## Run (stdio — for a local MCP client)

```bash
uv run jk-mcp-ecnl
```

The server speaks MCP over stdin/stdout. Point your MCP client at the command
above. Never print to stdout from tool code in this mode — it corrupts the
JSON-RPC stream.

## Run (HTTP — for a networked deployment)

```bash
MCP_TRANSPORT=streamable-http HOST=0.0.0.0 PORT=8000 uv run jk-mcp-ecnl
```

Health probes: `GET /livez`, `GET /readyz`, `GET /health`.

## A typical tool sequence

1. `find_events(league="ECNL", gender="girls")` → pick an event ID.
2. `get_event_overview(event_id)` → read the division and flight IDs.
3. `get_standings(event_id, division_id, flight_id)` — the table.
4. `get_schedule(event_id, flight_id)` — fixtures and results.
5. `get_rpi(event_id, flight_id)` — RPI ranking with WP/OWP/OOWP breakdown.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `MCP_TRANSPORT` | `stdio` | `stdio` or `streamable-http` |
| `HOST` | `0.0.0.0` | bind address (HTTP transport) |
| `PORT` | `8000` | TCP port (HTTP transport) |
| `MCP_PATH` | `/mcp/ecnl` | URL path (HTTP transport) |
| `API_HOST` | `https://api.athleteone.com` | upstream API base URL |
| `LOG_LEVEL` | `INFO` | logging level |

## Development

```bash
uv run inv lint              # ruff check + format check
uv run inv check-complexity  # cyclomatic complexity gate (max 7)
uv run inv coverage          # pytest + coverage (min 90%)
```
