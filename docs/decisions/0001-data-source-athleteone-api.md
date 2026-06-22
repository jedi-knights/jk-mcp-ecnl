# 1. Data source: the AthleteOne (Total Global Sports) public API

Date: 2025-06-22

## Status

Accepted

## Context

theecnl.com publishes ECNL and ECRL schedules and standings for boys and girls,
across many age groups and conferences. We needed a programmatic data source for
an MCP server. theecnl.com itself is an Angular single-page app and exposes no
documented API.

## Decision

Use the **public JSON REST API at `https://api.athleteone.com/api/`**, the
backend that powers the Total Global Sports / AthleteOne platform behind
theecnl.com. It was reverse-engineered from the site's JS bundle and verified
with live requests.

Key findings (verified with `curl`, no authentication required — the site's own
Angular HTTP interceptor attaches no auth header to public calls):

### Data hierarchy

`league (ECNL/ECRL) × gender (boys/girls) × conference × season` = one **event**
(`eventID`). Within an event, **divisions** are age groups (e.g. `G2008/2007`),
each containing one or more **flights**; standings and schedules are keyed by
`flightID`. The event *name* encodes league/gender/conference/season — ECRL is
spelled "ECNL RL" (e.g. `"ECNL RL Girls STXCL 2025-26"`).

### Verified endpoints (all GET, envelope `{"result":"success","data":...}`)

| Purpose | Path |
|---|---|
| Event metadata | `team/get-event-details-by-eventid/{eventID}` |
| Division/flight index | `Event/get-event-schedule-or-standings/{eventID}` |
| Standings | `Event/get-standings-by-div-and-flight/{divisionID}/{flightID}/{eventID}` |
| Schedule | `Event/get-schedules-by-flight/{eventID}/{flightID}/0` |
| Teams in a flight | `Event/get-team-list-by-flight/{flightID}` |
| Teams in an event | `Event/get-team-list/{eventID}` |
| Clubs in an event | `Event/get-org-club-list-by-event/{eventID}` |
| Team schedule | `Event/get-game-list-by-eventID-and-teamID/{eventID}/{teamID}` |
| Match detail | `Event/get-match-detail-by-token/{token}` |
| Brackets | `Event/get-flight-brackets-by-flight/{eventID}/{flightID}` |
| Org club list (discovery) | `Event/get-org-club-list-by-orgID/{orgID}` |

### Event discovery

There is **no public "list all events" endpoint**. The site navigates from
links on theecnl.com. We discovered that `get-org-club-list-by-orgID/{orgID}`
returns every club with the `eventID` it competes in (0 if none) plus the
current `orgSeasonID`. So discovery walks the four league/gender orgs, collects
each club's event ID, and classifies each event by name.

The four organization IDs (resolved by probing `get-org-club-list-by-orgID` for
org IDs 1–20 and reading a sample event name from each):

| orgID | league | gender | sample event |
|---|---|---|---|
| 9  | ECNL | girls | "ECNL Girls Southeast 2025-26" |
| 12 | ECNL | boys  | "ECNL Boys Northern Cal 2025-26" |
| 13 | ECRL | girls | "ECNL RL Girls STXCL 2025-26" |
| 16 | ECRL | boys  | "ECNL RL Boys Golden State 2025-26" |

These IDs are stable identifiers, not data; they live in `discovery.py`'s
`_ORG_IDS` seed and can be re-derived with the probe above if the league
restructures.

## Consequences

- **No auth, clean JSON** — the adapter mirrors `jk-mcp-nwsl`'s ESPN adapter:
  one reused `httpx.AsyncClient`, envelope unwrap, HTTP→domain error mapping.
- **Match detail and bracket payloads are returned raw** (pretty-printed JSON)
  because their shapes vary by event and are not worth normalizing in v1.
- **RPI within a single flight ≈ winning percentage.** Most flights are complete
  round-robins, so OWP and OOWP converge to ~0.5 for every team and add little
  discrimination. Cross-conference / national RPI pools (which need data from
  multiple events) would make OWP/OOWP meaningful and are deferred to a future
  iteration; v1 rates within the flight, which is correct and fully available.
- **RPI lineage.** The math is modeled on the sibling `ratings` repo's
  match-based stats but reimplemented here to (a) handle ties in WP per the
  formula at sites.google.com/site/rpifordivisioniwomenssoccer/rpi-formula
  (tie = 1/3 in 2024, configurable), and (b) compute all teams in one O(V+E)
  pass. We did not take a path dependency on `ratings` (Python 3.8, unpackaged).
