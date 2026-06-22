# jk-mcp-ecnl

[![CI](https://github.com/jedi-knights/jk-mcp-ecnl/actions/workflows/ci.yml/badge.svg)](https://github.com/jedi-knights/jk-mcp-ecnl/actions/workflows/ci.yml)
[![Badge](https://github.com/jedi-knights/jk-mcp-ecnl/actions/workflows/badge.yml/badge.svg)](https://github.com/jedi-knights/jk-mcp-ecnl/actions/workflows/badge.yml)
[![Coverage](https://img.shields.io/badge/Coverage-92.5%25-brightgreen)](https://jedi-knights.github.io/jk-mcp-ecnl/)
[![Python](https://img.shields.io/badge/python-3.13-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

AI assistants like Claude have a knowledge cutoff — they can't tell you today's ECNL standings, last weekend's scores, or how your club's team is doing in its conference right now. This project fixes that.

It is an **MCP server** — a plugin that gives Claude direct access to live **ECNL** (Elite Clubs National League) and **ECRL** (ECNL Regional League) youth-soccer data: schedules, standings, results, teams, clubs, and RPI ratings, for both boys and girls across every conference and age group. Once connected, you can ask Claude natural-language questions and get accurate, up-to-date answers. No subscription, no API key, and no programming required to use it.

Built as a sibling to [`jk-mcp-nwsl`](https://github.com/jedi-knights/jk-mcp-nwsl): Python 3.13, FastMCP, `httpx`, hexagonal architecture. Data comes from the public Total Global Sports / AthleteOne API that powers [theecnl.com](https://theecnl.com/).

---

## Contents

- [Data model](#data-model)
- [Tools](#tools)
- [Example prompts](#example-prompts)
- [Production](#production)
- [Requirements](#requirements)
- [Quickstart](#quickstart)
- [Configuration](#configuration)
- [Claude Code](#claude-code)
- [Claude Desktop](#claude-desktop)
- [Docker](#docker)
- [Development](#development)
- [Contributing](#contributing)
- [License](#license)

---

## Data model

`league (ECNL/ECRL) × gender (boys/girls) × conference × season` is one **event**
(`event_id`). Within an event, **divisions** are age groups (e.g. `G2008/2007` ≈ "U17"),
each with one or more **flights**; standings and schedules are keyed by `flight_id`.
Start with `find_events` to turn a human description into the IDs the other tools
need — Claude does this chaining for you, so you never supply IDs by hand.

---

## Tools

| Tool | Description |
|---|---|
| `find_events` | Find ECNL/ECRL events (conferences) by league, gender, and/or season → event IDs |
| `get_event_overview` | List an event's divisions and flights with their IDs, tier, and team counts |
| `get_standings` | Get a flight's standings table — W-L-D, points, points-per-game |
| `get_schedule` | Get all matches for a flight — date, venue, teams, score |
| `get_team_schedule` | Get one team's matches within an event |
| `get_teams` | List the teams in a flight |
| `get_clubs` | List the clubs participating in an event |
| `get_match` | Get a single match's detail / box score |
| `get_brackets` | Get a flight's playoff bracket, if one exists |
| `get_results` | Get completed match results for a flight (the input RPI builds on) |
| `get_rpi` | Compute the RPI ranking for a flight with WP/OWP/OOWP components |
| `get_team_rpi` | Compute one team's RPI with its component breakdown |

All tools are read-only and idempotent. Data comes from the **AthleteOne / Total Global
Sports public API** (`api.athleteone.com`) that powers theecnl.com — no auth required, but
the contract is not officially documented; if a tool stops working the upstream format
likely changed. Endpoints, the org IDs used for event discovery, and the data hierarchy
are documented in [docs/decisions/0001-data-source-athleteone-api.md](docs/decisions/0001-data-source-athleteone-api.md).

### RPI

`get_rpi` and `get_team_rpi` compute the Rating Percentage Index using the standard NCAA
structure from [the women's-soccer RPI reference](https://sites.google.com/site/rpifordivisioniwomenssoccer/rpi-formula):

```
RPI = 0.25·WP + 0.50·OWP + 0.25·OOWP
```

`WP = (W + tie_weight·T) / (W + L + T)`, with `tie_weight` defaulting to `1/3` (the 2024
convention; pass `0.5` for the pre-2024 convention). OWP and OOWP score ties at `1/2` and
exclude the rated team from each opponent's record. Note: within a single conference
(typically a complete round-robin) OWP/OOWP converge to ~0.5, so RPI ≈ WP there — RPI's
discriminating power comes from cross-conference pools, a planned future enhancement.

---

## Example prompts

Once the server is connected, ask Claude natural-language questions — it chains the tools
for you (typically `find_events` → `get_event_overview` → `get_standings`/`get_schedule`/`get_rpi`),
resolving the event, division, and flight IDs along the way. Age groups map to birth-year
divisions (e.g. "U17" ≈ the `G2008/2007` division).

### Discovering events

> What ECNL girls conferences are there this season?

> List the ECRL boys events for 2025-26.

> Is there an ECNL boys conference in Northern California?

### Standings

> Show me the ECNL Girls Southwest U17 standings.

> Who's top of the table in ECNL Boys Northern Cal U16?

> How many points separate the top three teams in ECRL Girls Carolinas?

### Schedules and results

> What's the schedule for the ECNL Girls Southeast U15 flight?

> What were last weekend's scores in ECNL Boys Texas U17?

> When does Slammers FC HB Koge play next?

> Give me Beach FC's results so far this season.

### Teams and clubs

> Which clubs are competing in the ECNL Girls Southwest event?

> List the teams in the ECNL Boys Northern Cal U16 flight.

### RPI analysis

> Rank the ECNL Girls Southwest U17 flight by RPI.

> What's Slammers FC's RPI, broken down into WP, OWP, and OOWP?

> Recompute that flight's RPI using the pre-2024 ½ tie weight.

> In ECRL Boys Carolinas, which team has faced the strongest opponents (highest OWP)?

### Playoffs

> Is there a playoff bracket for the ECNL Girls Southwest U19 flight?

---

## Production

A live instance runs on Fly.io behind the
[api-gateway](https://github.com/jedi-knights/api-gateway). The MCP server itself is
private (no public address) — all access goes through the gateway:

```
https://jk-api-gateway.fly.dev/mcp/ecnl
```

No installation, no Python, no cloning required. Point your MCP client at the URL above and you are done.

### Claude Code

Install globally (recommended) so the server is available in every project:

```sh
claude mcp add --transport http --scope user ecnl https://jk-api-gateway.fly.dev/mcp/ecnl
```

Verify it's registered and healthy:

```sh
claude mcp list
```

You should see `ecnl: https://jk-api-gateway.fly.dev/mcp/ecnl (HTTP) - ✓ Connected`. Restart Claude Code if you had it open.

**Other scopes:**

- Drop `--scope user` to register only for the current project (`cwd` must match when you run `claude`).
- Or commit a `.mcp.json` to the repo root to share with collaborators:

  ```json
  {
    "mcpServers": {
      "ecnl": {
        "type": "http",
        "url": "https://jk-api-gateway.fly.dev/mcp/ecnl"
      }
    }
  }
  ```

### Claude Desktop

Add the following to your Claude Desktop configuration file.

**Location:**
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "ecnl": {
      "type": "streamable-http",
      "url": "https://jk-api-gateway.fly.dev/mcp/ecnl"
    }
  }
}
```

Restart Claude Desktop after saving. The ECNL tools will appear in the tool picker.

---

## Requirements

- [Python 3.13+](https://www.python.org/downloads/)
- [uv](https://docs.astral.sh/uv/getting-started/installation/)

Only needed to run the server locally — the [hosted instance](#production) requires neither.

---

## Quickstart

```sh
git clone https://github.com/jedi-knights/jk-mcp-ecnl.git
cd jk-mcp-ecnl
uv sync
```

Run the server in stdio mode (the default — used by Claude Code and Claude Desktop):

```sh
uv run python -m ecnl.server
```

Run in HTTP mode (for networked or deployed access):

```sh
MCP_TRANSPORT=streamable-http uv run python -m ecnl.server
```

The installed entry point `jk-mcp-ecnl` is equivalent to `python -m ecnl.server`.

---

## Configuration

All configuration is via environment variables. None are required for local use.

| Variable | Default | Description |
|---|---|---|
| `MCP_TRANSPORT` | `stdio` | Transport mode: `stdio` or `streamable-http` |
| `HOST` | `0.0.0.0` | Bind address (HTTP transport only) |
| `PORT` | `8000` | TCP port (HTTP transport only) |
| `MCP_PATH` | `/mcp/ecnl` | URL path served (streamable-http transport only) |
| `API_HOST` | `https://api.athleteone.com` | AthleteOne / TGS API base URL |
| `LOG_LEVEL` | `INFO` | Log level: `DEBUG`, `INFO`, `WARNING`, `ERROR` |

---

## Claude Code

> Prefer the hosted server? See [Production → Claude Code](#claude-code) above — it's a single command and requires no clone.

To run the server from your local clone instead, install it globally:

```sh
claude mcp add --scope user ecnl -- uv run --directory /path/to/jk-mcp-ecnl python -m ecnl.server
```

Replace `/path/to/jk-mcp-ecnl` with the absolute path to your clone. Verify with `claude mcp list`.

**Other scopes:**

- Drop `--scope user` to register only for the current project.
- Or commit a `.mcp.json` to the repo root for collaborators:

  ```json
  {
    "mcpServers": {
      "ecnl": {
        "command": "uv",
        "args": ["run", "--directory", "/path/to/jk-mcp-ecnl", "python", "-m", "ecnl.server"]
      }
    }
  }
  ```

See [Example prompts](#example-prompts) for ideas on what to ask.

---

## Claude Desktop

### Install Claude Desktop

**With Homebrew (macOS):**

```sh
brew install --cask claude
```

**Without Homebrew:**

Download the installer for your platform from [claude.ai/download](https://claude.ai/download) and follow the on-screen instructions:

- macOS: open the downloaded `.dmg` and drag **Claude** into `/Applications`
- Windows: run the downloaded `.exe` installer

Launch Claude Desktop once and sign in before continuing — this creates the configuration directory referenced below.

### Configure Claude Desktop to use this MCP server

Pick the option that matches how you want to run the server: **hosted** (no install), **uv** (local clone), or **Docker** (containerized). Then follow the four steps below.

#### 1. Open the Claude Desktop config file

The fastest way is from inside Claude Desktop: **Settings → Developer → Edit Config**. This opens (and creates, if needed) the file in your default editor.

You can also open it directly:

- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

If the file does not exist yet, create it with `{}` as its contents.

#### 2. Add the `ecnl` server entry

Merge **one** of the following snippets into the top-level `mcpServers` object. If `mcpServers` does not exist, add the whole block as shown.

**Option A — Hosted (easiest, no install):**

```json
{
  "mcpServers": {
    "ecnl": {
      "type": "streamable-http",
      "url": "https://jk-api-gateway.fly.dev/mcp/ecnl"
    }
  }
}
```

**Option B — Local clone with `uv`:**

Replace `/path/to/jk-mcp-ecnl` with the absolute path to your clone. If `uv` is not on Claude Desktop's `PATH`, use the absolute path to the binary (`which uv` will show it — typically `/opt/homebrew/bin/uv` on Apple Silicon or `/usr/local/bin/uv` on Intel Macs).

```json
{
  "mcpServers": {
    "ecnl": {
      "command": "uv",
      "args": [
        "run",
        "--directory", "/path/to/jk-mcp-ecnl",
        "python", "-m", "ecnl.server"
      ]
    }
  }
}
```

**Option C — Docker:**

Build the image first (see [Docker](#docker)), then:

```json
{
  "mcpServers": {
    "ecnl": {
      "command": "docker",
      "args": ["run", "-i", "--rm", "jk-mcp-ecnl:latest"]
    }
  }
}
```

#### 3. Save and fully restart Claude Desktop

Quit Claude Desktop completely (**⌘Q** on macOS, or right-click the tray icon → **Quit** on Windows) and relaunch it. A simple window close is not enough — the MCP servers are only loaded on launch.

#### 4. Verify the connection

Open a new chat and click the tools / plug icon in the message bar. You should see **ecnl** listed with its tools (`find_events`, `get_standings`, `get_schedule`, `get_rpi`, and more). Try a prompt from [Example prompts](#example-prompts) to confirm it works end-to-end.

If the server does not appear, check the Claude Desktop logs:

- **macOS:** `~/Library/Logs/Claude/mcp*.log`
- **Windows:** `%APPDATA%\Claude\logs\mcp*.log`

---

## Docker

Build the image:

```sh
docker build -t jk-mcp-ecnl:latest .
```

Run in stdio mode (for MCP clients that spawn a subprocess):

```sh
docker run -i --rm jk-mcp-ecnl:latest
```

Run in HTTP mode:

```sh
docker run --rm -p 8000:8000 \
  -e MCP_TRANSPORT=streamable-http \
  jk-mcp-ecnl:latest
```

---

## Development

### Install dependencies

```sh
uv sync
```

### Invoke tasks

All common development workflows are available as `invoke` tasks. Run `uv run inv --list` to see all tasks.

| Task | Alias | Description |
|---|---|---|
| `uv run inv install` | `inv i` | Install project dependencies |
| `uv run inv lint` | `inv l` | Run ruff linter and format check |
| `uv run inv lint --fix` | `inv l --fix` | Auto-fix lint violations and reformat |
| `uv run inv test` | `inv t` | Run the full test suite |
| `uv run inv test -k <expr>` | `inv t -k <expr>` | Run tests matching an expression |
| `uv run inv test -x` | `inv t -x` | Stop after the first failure |
| `uv run inv coverage` | `inv v` | Run tests with coverage report (threshold: 90%) |
| `uv run inv check-complexity` | `inv cc` | Check cyclomatic complexity (max 7) |
| `uv run inv build` | `inv b` | Build wheel and sdist into `dist/` |
| `uv run inv build-image` | `inv bi` | Build the Docker image |
| `uv run inv clean` | `inv c` | Remove build and coverage artifacts |

### Workflow

```sh
# Make changes, then verify everything passes before committing
uv run inv lint
uv run inv check-complexity
uv run inv coverage
```

### Project structure

```
src/ecnl/
├── server.py                       # entry point, transport selection, logging
├── adapters/
│   ├── inbound/
│   │   ├── mcp_adapter.py          # FastMCP server wiring + health routes
│   │   ├── formatters.py           # domain models → text output
│   │   └── tools/                  # tool groups: events, standings, schedule, teams, matches, analytics
│   └── outbound/
│       ├── athleteone_adapter.py   # AthleteOne (TGS) HTTP client
│       ├── athleteone_parsers.py   # wire JSON → domain models
│       ├── discovery.py            # org-walk event discovery
│       ├── retry_adapter.py        # retry decorator for transient failures
│       └── caching_adapter.py      # in-process TTL cache
├── application/
│   ├── service.py                  # use cases, orchestration, RPI table memo
│   └── _rpi.py                     # pure RPI engine (WP / OWP / OOWP)
├── domain/
│   ├── models.py                   # Event, Division, Flight, Standings, Match, TeamRPI, …
│   ├── classification.py           # event name → league / gender / conference / season
│   └── exceptions.py               # ECNLNotFoundError, UpstreamAPIError
└── ports/
    └── outbound.py                 # ECNLAPIPort, DiscoveryPort protocols
```

The dependency direction flows inward: adapters → ports → domain. Nothing in `domain/` imports from adapters or the framework. See [docs/decisions/0001-data-source-athleteone-api.md](docs/decisions/0001-data-source-athleteone-api.md) for how the data source and event discovery work.

---

## Contributing

1. Fork the repository and clone your fork
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Make your changes following the existing patterns (hexagonal architecture, TDD, conventional commits)
4. Verify the full check suite passes: `uv run inv lint && uv run inv check-complexity && uv run inv coverage`
5. Open a pull request against `main`

All CI checks (lint, complexity, tests, coverage ≥ 90%) must pass before merge.

---

## License

MIT — see [LICENSE](LICENSE).
