# jk-mcp-ecnl

An MCP server for **ECNL** (Elite Clubs National League) and **ECRL** (ECNL
Regional League) youth soccer — schedules, standings, and RPI for both boys and
girls — backed by the public Total Global Sports / AthleteOne API that powers
[theecnl.com](https://theecnl.com/).

Built as a sibling to [`jk-mcp-nwsl`](../jk-mcp-nwsl): Python 3.13, FastMCP,
`httpx`, hexagonal architecture.

## Contents

- [Features](#features)
- [Data model](#data-model)
- [Requirements](#requirements)
- [Quickstart](#quickstart)
- [Configuration](#configuration)
- [Tools](#tools)
- [Development](#development)
- [How it works](#how-it-works)
- [License](#license)

## Features

- Discover ECNL/ECRL events (conferences) by league, gender, and season — no
  event IDs to memorize.
- Standings, schedules, results, teams, clubs, match detail, and playoff
  brackets for any flight.
- **RPI** (Rating Percentage Index) computed from extracted match results, with
  the WP / OWP / OOWP breakdown and a configurable tie weight.
- Read-only, idempotent tools over a public, no-auth JSON API.

## Data model

`league (ECNL/ECRL) × gender (boys/girls) × conference × season` is one **event**
(`event_id`). Within an event, **divisions** are age groups, each with one or
more **flights**; standings and schedules are keyed by `flight_id`. Start with
`find_events` to turn a human description into the IDs the other tools need.

## Requirements

- Python 3.13+
- [uv](https://docs.astral.sh/uv/)

## Quickstart

```bash
uv sync
uv run jk-mcp-ecnl          # stdio transport (default)
```

See [docs/quickstart.md](docs/quickstart.md) for HTTP mode and a typical tool
sequence.

### Claude Code / Claude Desktop

Register the server as a stdio MCP server running `uv run jk-mcp-ecnl` from this
directory (or `docker run -i --rm jk-mcp-ecnl`).

### Docker

```bash
uv run inv build-image            # build jk-mcp-ecnl:latest
docker run -i --rm jk-mcp-ecnl    # stdio
docker compose up                 # HTTP on :8000
```

## Configuration

All configuration is via environment variables — see the table in
[docs/quickstart.md](docs/quickstart.md#configuration).

## Tools

| Tool | What it returns |
|---|---|
| `find_events` | Events (conferences) matching league/gender/season → event IDs |
| `get_event_overview` | An event's divisions and flights, with flight IDs and tiers |
| `get_standings` | A flight's standings table (W-L-D, points, PPG) |
| `get_schedule` | All matches for a flight |
| `get_team_schedule` | One team's matches within an event |
| `get_teams` | Teams in a flight |
| `get_clubs` | Clubs in an event |
| `get_match` | Match detail / box score (raw JSON) |
| `get_brackets` | Playoff bracket for a flight (raw JSON) |
| `get_results` | Completed match results for a flight (the RPI input) |
| `get_rpi` | RPI ranking for a flight with WP/OWP/OOWP components |
| `get_team_rpi` | One team's RPI breakdown |

### RPI

RPI follows the standard NCAA structure used by
[the women's-soccer RPI reference](https://sites.google.com/site/rpifordivisioniwomenssoccer/rpi-formula):

```
RPI = 0.25·WP + 0.50·OWP + 0.25·OOWP
```

`WP = (W + tie_weight·T) / (W + L + T)` with `tie_weight` defaulting to 1/3 (the
2024 convention; pass `0.5` for pre-2024). OWP and OOWP score ties at 1/2 and
exclude the rated team from each opponent's record. Note: within a single
conference (typically a complete round-robin) OWP/OOWP converge to ~0.5, so RPI
≈ WP there — RPI's discriminating power comes from cross-conference pools, a
planned future enhancement (see the ADR).

## Development

```bash
uv run inv lint              # ruff check + format check
uv run inv check-complexity  # cyclomatic complexity gate (max 7)
uv run inv coverage          # pytest + coverage (min 90%)
```

## How it works

Hexagonal architecture — the dependency graph flows inward:

```
adapters/inbound (FastMCP tools, formatters)
        │
   application (ECNLService, RPI engine)
        │
      ports (ECNLAPIPort, DiscoveryPort)
        │
     domain (models, classification, exceptions)
        ▲
adapters/outbound (AthleteOneAdapter, retry, cache, discovery)
```

The data source, its quirks, and how event discovery works are documented in
[docs/decisions/0001-data-source-athleteone-api.md](docs/decisions/0001-data-source-athleteone-api.md).

## License

See [LICENSE](LICENSE).
