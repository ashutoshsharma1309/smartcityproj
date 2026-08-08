# UrbanPulse architecture

## 1. The problem

Urban waterlogging is not primarily a rainfall problem — it is a rainfall
problem *interacting with terrain, drainage and impervious ground*. The same
80 mm of rain floods a low, flat, paved ward with saturated soil at high tide,
and drains harmlessly off a sloped one. Cities respond after water has already
accumulated, because nobody is holding those factors together in one place.

UrbanPulse predicts, per zone and a few hours ahead, the probability that
waterlogging occurs; then derives which roads that cuts, and what a municipal
team should do about it.

## 2. Design commitments

Four commitments shape every decision below.

**Numbers come from models, prose comes from the LLM.** The risk score, the
feature attributions, the affected road lengths and the connectivity analysis
are all computed by deterministic code. The LLM receives those finished
numbers and writes a paragraph. It is the last stage in the chain and can be
removed entirely without the platform losing a capability.

**Absent data is reported, never filled in.** Every capability that lacks its
inputs returns `501 Not Implemented` or `409 Data Unavailable` with the missing
module named. There is no sample data, no placeholder prediction, and no
demo mode that looks like a real forecast.

**Provenance is enforced by the schema.** Every observation row carries a
foreign key to `data_sources`, which records provider, licence and an `origin`
of `observed`, `derived` or `simulated`. It is not possible to store a
measurement without saying where it came from.

**Heavy work happens offline.** Anything that needs GeoPandas, rasterio or a
training runtime is a batch job. The API reads results from PostGIS.

## 3. Component map

```
                            ┌────────────────────────────┐
                            │  Public data providers     │
                            │  Open-Meteo · OSM/Overpass │
                            │  Copernicus DEM            │
                            └─────────────┬──────────────┘
                                          │ HTTPS
                    ┌─────────────────────▼─────────────────────┐
                    │  OFFLINE PIPELINE  (batch, CPU-only)      │
                    │                                           │
                    │  Ingestion ─▶ Validation ─▶ Geospatial     │
                    │       │                        │           │
                    │       └──▶ Features ──▶ Training           │
                    │                            │               │
                    │                     model artefact         │
                    └───────────────┬───────────────┬───────────┘
                                    │ writes        │ loads
                    ┌───────────────▼───────────────▼───────────┐
                    │  PostgreSQL 16 + PostGIS 3.4              │
                    │  data_sources · zones · road_segments     │
                    │  weather_observations · flood_incidents   │
                    └───────────────┬───────────────────────────┘
                                    │ reads
                    ┌───────────────▼───────────────────────────┐
                    │  FastAPI  (async, thin)                   │
                    │                                           │
                    │  Risk ─▶ Impact ─▶ Recommendations ─▶ LLM │
                    │    ▲                                      │
                    │  Redis cache · viewport aggregations      │
                    └───────────────┬───────────────────────────┘
                                    │ REST + GeoJSON
                    ┌───────────────▼───────────────────────────┐
                    │  Next.js + MapLibre command centre        │
                    └───────────────────────────────────────────┘
```

## 4. Component responsibilities

| # | Component | Responsibility | Status |
|---|-----------|----------------|--------|
| 1 | Data Ingestion | Fetch from registered providers; write an audited `ingestion_runs` row per attempt | Interface only |
| 2 | Data Validation | Schema, range and geometry-topology checks; count rejections per reason | Interface only |
| 3 | Geospatial Processing | Build zones and the road graph; derive terrain attributes from the DEM | Read paths live; derivation Phase 2 |
| 4 | Feature Engineering | Build the shared feature matrix from `ml/features/specification.py` | Interface only |
| 5 | Risk Prediction | LightGBM classifier → calibrated probability + SHAP attributions | Interface only |
| 6 | Impact Analysis | Intersect at-risk zones with roads; NetworkX connectivity for severed links | Interface only |
| 7 | Recommendation | Deterministic rules → auditable municipal actions | Interface only |
| 8 | LLM Explanation | Structured facts → prose. Provider-agnostic | Interface + prompt layer built |
| 9 | Alert / Event | Threshold crossings → events | Interface only |
| 10 | REST API | Versioned surface, one error envelope, request correlation | Live |
| 11 | GIS Frontend | Map, live backend status, data catalogue | Live |
| 12 | Evaluation | Backtesting, calibration, drift | Interface only |

`GET /api/v1/meta` returns this table's status column at runtime, and the
dashboard renders it directly — so the UI cannot claim a capability the backend
does not have.

## 5. Data flow

### Ingestion (batch, scheduled)

```
provider API ──▶ validate ──▶ resolve data_source by slug ──▶ write rows
                    │                     │
                    │                     └── refuses unregistered slugs
                    └── rejects out-of-range / bad-topology records, counted per run
```

Every run writes an `ingestion_runs` row — including failures, with the error
message and the request parameters used, so a run can be reproduced.

### Prediction (request or scheduled)

```
zones ─┐
       ├──▶ feature matrix ──▶ LightGBM ──▶ probability
weather┘                          │
                                  └──▶ SHAP ──▶ top contributions
                                                      │
                              road_segments ──▶ impact analysis
                                                      │
                                              rules engine ──▶ actions
                                                      │
                                            LLM (optional) ──▶ prose
```

Every stage before the LLM is deterministic and reproducible from stored data.

## 6. API design

`/health`, `/health/db` and `/health/ready` sit outside the version prefix —
orchestrators probe them, and probe URLs should not move when the API version
does. Everything else lives under `/api/v1`.

Health probes always return **200** and describe dependency state in the body.
A probe that returns 503 when the database is down is indistinguishable from
the probe itself being broken.

`/health/db` explicitly asserts that the PostGIS extension is installed, not
just that PostgreSQL answers. A reachable database without PostGIS would fail
every geospatial query at runtime while a `SELECT 1` reported health.

Errors use one envelope everywhere:

```json
{"error": {"code": "not_implemented", "message": "...",
           "details": {"module": "risk_prediction", "planned_phase": "Phase 3"},
           "request_id": "..."}}
```

| Status | Meaning |
|--------|---------|
| 409 `data_unavailable` | The analysis is implemented but its input data has not been ingested |
| 501 `not_implemented` | The module is an interface with no implementation yet |
| 502 `external_service_error` | An upstream provider or the LLM failed |
| 503 `service_unavailable` | A dependency is unreachable |

The distinction between 409 and 501 matters: one says "we can do this, we lack
data", the other says "we have not built this".

## 7. Data model

`data_sources` is the root of the graph. Every observational table has a
non-nullable FK to it, which makes unattributed data unrepresentable.

```
data_sources ──┬──▶ ingestion_runs
               ├──▶ zones ──┬──▶ road_segments
               │            ├──▶ weather_observations
               │            └──▶ flood_incidents
               ├──▶ drainage_assets
               └──▶ tide_observations
```

All geometry is EPSG:4326 with GIST indexes. Derived terrain columns on `zones`
are nullable — they stay `NULL` until the geospatial pipeline runs, rather than
defaulting to zero, because zero elevation is a claim and `NULL` is not.

## 8. Technology choices

**PostgreSQL + PostGIS.** The core queries are spatial joins between zone
polygons and road lines. Doing that in application code would mean pulling
geometry into Python; PostGIS does it with an index.

**Async FastAPI, sync Alembic.** The API is I/O-bound so async pays off.
Migrations are a one-shot batch job where async buys nothing and complicates
tooling, so they use psycopg synchronously.

**LightGBM over deep learning.** Small tabular feature set, CPU-only laptop,
and exact SHAP attributions. A neural network would be slower to train, harder
to explain and no more accurate here.

**Redis.** Two real jobs: caching viewport-keyed PostGIS aggregations that
change only when ingestion runs but are requested on every map pan, and (from
Phase 2) brokering scheduled ingestion. It degrades to a no-op when disabled —
`REDIS_ENABLED=false` still yields a working API.

**MapLibre GL.** BSD-licensed, no vendor lock-in, consumes the GeoJSON PostGIS
already produces.

**Server-side geometry simplification.** `ST_SimplifyPreserveTopology` runs in
the database so large ward polygons do not ship megabytes of vertices to the
browser, and the API keeps no GEOS dependency.

## 9. LLM integration

The application depends on a narrow `LLMProvider` protocol
(`app/services/llm/provider.py`), never a vendor SDK, so providers swap by
configuration. `NullLLMProvider` is the default and *raises* rather than
returning placeholder prose.

Two properties are enforced in code, not by prompt instructions alone:

1. `ExplanationService.explain` takes a validated `ExplanationRequest` — no
   free-form text can reach the model, and it has no path to produce a number
   that enters the system.
2. `build_user_prompt` serialises only fields present on that object, and
   states missing inputs explicitly rather than omitting them. Omission would
   let the model imply an input was fine when it was absent.

Requests carry no message history. Each call is stateless and self-contained,
so the model cannot carry a value over from a previously explained zone.

Responses echo a `grounded_on` block containing the facts the text was built
from, so output can be audited against its inputs after the fact.

## 10. Future: real-time

Phase 5 replaces polling with a push path:

```
scheduled ingestion (Redis broker)
        │
        ▼
  risk recomputation ──▶ threshold check ──▶ alert event
        │                                        │
        ▼                                        ▼
  Redis pub/sub ──────────────────▶ FastAPI WebSocket ──▶ dashboard
```

REST stays the source of truth for the current state; the socket carries
deltas. The frontend already re-fetches on load and treats a failed request as
displayable state, so adding a socket does not require reworking it.

## 11. Deliberate non-goals

- **No Kubernetes.** Docker Compose is sufficient at this scale; orchestration
  would be complexity without a corresponding problem.
- **No microservices.** One API process with clear internal module boundaries.
  Those boundaries are where a service could later be split off, if load ever
  justified it.
- **No local LLM inference.** A hard constraint of the target hardware, and the
  LLM is not on the critical path anyway.
- **No authentication yet.** Phase 6. Adding it now, before there is anything
  to protect, would be premature.
