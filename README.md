# UrbanPulse

**Predictive urban flood risk and road impact.**

UrbanPulse forecasts the probability of waterlogging for each zone of a city a
few hours ahead, works out which roads that cuts, explains what is driving the
forecast, and recommends what a municipal team should do.

> **Phase 1 (current).** The foundation runs: containerised PostGIS and Redis,
> a versioned FastAPI backend, provenance-enforcing schema and migrations, a
> test suite, and a MapLibre command centre that renders live backend state.
> The risk model is **not** built yet, so every prediction endpoint returns
> `501 Not Implemented` naming the module and the phase that will deliver it.
> Nothing in this repository fabricates a forecast.

---

## The problem

Waterlogging is not simply a rainfall problem — it is rainfall *interacting
with* terrain, drainage capacity and impervious ground. The same 80 mm floods a
low, flat, paved ward with saturated soil at high tide and drains harmlessly
off a sloped one. Cities react after water has accumulated, because nobody
holds those factors together in one view.

UrbanPulse holds them together, and says which roads will be affected before
they are.

## What this is not

- Not a ChatGPT wrapper. The LLM is the **last** stage and writes prose from
  finished numbers. Remove it and the platform loses no analytical capability.
- Not a demo with fake data. Absent data produces an explicit error, never a
  plausible-looking number.
- Not a static dashboard. Every panel reflects live backend state.

## How the intelligence is arranged

```
real data → validation → geospatial → features → ML risk score
          → impact analysis → recommended actions → LLM explanation
```

The LLM receives structured facts and returns a paragraph. It never produces a
probability, a coordinate, a weather value or a road condition. When the data
needed to answer does not exist, the system says so.

---

## Architecture

```
Open-Meteo · OpenStreetMap · Copernicus DEM
                 │
      OFFLINE PIPELINE (batch, CPU-only)
   ingest → validate → geospatial → features → train
                 │
   PostgreSQL 16 + PostGIS 3.4  ◀── provenance-enforcing schema
                 │
      FastAPI (async, thin)  +  Redis cache
                 │  REST / GeoJSON
      Next.js + MapLibre command centre
```

Heavy geospatial and ML work runs offline; the API reads results from PostGIS.
That is why `backend/pyproject.toml` has no GeoPandas or LightGBM — they live
in `ml/requirements.txt`.

Full detail: [`docs/architecture.md`](docs/architecture.md).
Remaining phases: [`docs/development-roadmap.md`](docs/development-roadmap.md).

### Provenance is enforced by the schema

Every observational row has a non-nullable foreign key to `data_sources`, which
records provider, licence, and an `origin` of `observed`, `derived` or
`simulated`. Storing an unattributed measurement is not representable, and the
API exposes `origin` so the UI can badge simulated data distinctly.

Datasets are declared in
[`data/metadata/data_sources.json`](data/metadata/data_sources.json), which
also records **known gaps** — data the project needs and does not yet have,
including the historical incident records that the risk model's training label
depends on. That gap is why Phase 3 has not started.

---

## Technology

| Layer | Choice | Why |
|-------|--------|-----|
| Frontend | Next.js 15, TypeScript, Tailwind 4, MapLibre GL 5 | BSD-licensed maps, no vendor lock-in, consumes PostGIS GeoJSON directly |
| Backend | Python 3.12, FastAPI, SQLAlchemy 2 (async), Pydantic v2 | I/O-bound workload; typed contracts end to end |
| Database | PostgreSQL 16 + PostGIS 3.4 | Spatial joins belong in an indexed database, not in Python |
| Migrations | Alembic (sync psycopg) | Batch job; async adds nothing |
| Cache/broker | Redis 7 | Viewport aggregation cache; ingestion broker from Phase 2 |
| ML | LightGBM, scikit-learn, SHAP | Small tabular features, CPU-only, exact attributions |
| Geospatial | GeoPandas, Shapely, rasterio, NetworkX | Offline pipeline only |
| Logging | structlog | JSON in production, console locally, request-correlated |
| Infra | Docker Compose | Sufficient at this scale |

---

## Quick start

### Prerequisites

Docker, Node.js 20+, Python 3.12, and [uv](https://docs.astral.sh/uv/).

### Option A — everything in Docker

```bash
cp .env.example .env       # then set POSTGRES_PASSWORD
docker compose up -d --build
```

First boot takes a few minutes: PostGIS installs its extensions before the
database accepts connections, and the backend applies migrations on start.

- Dashboard → <http://localhost:3000>
- API docs → <http://localhost:8000/docs>

### Option B — services in Docker, apps on the host (faster iteration)

```bash
make install          # venv + backend deps + frontend deps
make up               # PostgreSQL/PostGIS + Redis
make migrate          # apply migrations
make seed-sources     # register the provenance manifest
make backend          # http://localhost:8000
make frontend         # http://localhost:3000   (separate terminal)
```

`make help` lists every target.

### Verify it works

```bash
curl -s localhost:8000/health/ready | python3 -m json.tool
```

Expect `status: "ok"` with `postgresql`, `postgis` and `redis` all `ok`.

```bash
make test        # backend suite
make typecheck   # frontend types
```

---

## Environment variables

Copy `.env.example` to `.env`. Every variable is documented there; the ones
that matter most:

| Variable | Default | Notes |
|----------|---------|-------|
| `POSTGRES_HOST` | `localhost` | `postgres` when the API runs inside Compose |
| `POSTGRES_PASSWORD` | — | **Set this.** No secret has a working default |
| `REDIS_ENABLED` | `true` | `false` disables caching; the API still works |
| `CORS_ORIGINS` | `http://localhost:3000,...` | Comma-separated browser origins |
| `LLM_PROVIDER` | `none` | `none` makes the explain endpoint report it is unconfigured |
| `LLM_API_KEY` | — | Without it, `llm_configured` is false regardless of provider |
| `CITY_NAME` / `CITY_BBOX` / `CITY_CENTER` | Mumbai | Nothing in the code is hardcoded to one city |
| `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:8000` | Resolved by the **browser**, so it must be host-visible |
| `API_BASE_URL_INTERNAL` | unset | Only needed under Compose, where the Next.js **server** cannot use `localhost`. Set for you in `docker-compose.yml` |

`.env` is gitignored. There are no secrets in the repository, and
`alembic.ini` deliberately contains no database URL — migrations build it from
the same `Settings` object the application uses.

---

## How the pieces talk

```
Browser ──▶ Next.js server component
                │  fetch() at request time, cache: "no-store"
                ▼
        FastAPI  http://localhost:8000
                │  asyncpg
                ▼
        PostgreSQL + PostGIS         Redis (cache)
```

The dashboard renders on the server on each request, so it always shows live
state. That has one consequence worth knowing: under Compose those fetches
leave the *frontend container*, where `localhost:8000` is the frontend itself.
Server-side calls therefore use `API_BASE_URL_INTERNAL`
(`http://backend:8000`), while the browser keeps using
`NEXT_PUBLIC_API_BASE_URL`. Running natively, both are `localhost` and only the
public one is needed.

`src/lib/api.ts` returns a discriminated result rather than throwing:
the backend being unreachable is *information the UI displays*, not an
exception to swallow. Stop the API and reload — the dashboard still renders and
tells you what is wrong.

CORS is configured for direct browser calls from `CORS_ORIGINS`; unlisted
origins are rejected, which the test suite asserts.

---

## API surface

| Endpoint | Purpose |
|----------|---------|
| `GET /health` | Liveness. Touches no dependencies |
| `GET /health/db` | PostgreSQL **and** PostGIS extension check |
| `GET /health/ready` | All dependencies aggregated |
| `GET /api/v1/meta` | Which modules are actually implemented |
| `GET /api/v1/catalog/sources` | Registered datasets with licence and origin |
| `GET /api/v1/catalog/summary` | Exact row counts per table |
| `GET /api/v1/geo/zones` | Zone polygons as GeoJSON |
| `GET /api/v1/geo/roads` | Road segments as GeoJSON |
| `GET /api/v1/risk/surface` | **501** until Phase 3 |
| `POST /api/v1/impact/assess` | **501** until Phase 4 |
| `POST /api/v1/explain` | Prose from computed facts; reports if no LLM configured |

Health probes always return 200 and describe dependency state in the body — a
probe returning 503 is indistinguishable from a broken probe.

Errors share one envelope:

```json
{"error": {"code": "not_implemented",
           "message": "City-wide risk surface generation is defined as an interface but has no implementation yet.",
           "details": {"module": "risk_prediction", "planned_phase": "Phase 3"},
           "request_id": "dfc6ea119eee4a3e98cafd01ab1b6c04"}}
```

`GET /api/v1/meta` is the honesty endpoint: it reports each module's real
state, and the dashboard renders it verbatim, so the UI cannot claim a
capability the backend lacks.

---

## Repository layout

```
urbanpulse/
├── backend/            FastAPI service
│   ├── app/
│   │   ├── api/        Routes: health + /api/v1
│   │   ├── core/       Config, logging, exceptions, middleware
│   │   ├── db/         Engine and session management
│   │   ├── models/     SQLAlchemy models (provenance, geography, observations)
│   │   ├── schemas/    Pydantic contracts
│   │   ├── services/   Pipeline modules + registry
│   │   ├── repositories/ Data access
│   │   └── cache/      Redis facade
│   ├── alembic/        Migrations
│   └── tests/          Pytest suite
├── frontend/           Next.js command centre
├── ml/                 Offline pipeline (separate dependency set)
│   └── features/specification.py   Shared feature contract
├── geospatial/         Batch geometry jobs
├── data/metadata/      Provenance manifest and known gaps
├── scripts/            Operational scripts
├── docker/             Dockerfiles
└── docs/               Architecture and roadmap
```

---

## Attribution

If you deploy this, you inherit these obligations:

- Weather data by [Open-Meteo.com](https://open-meteo.com) (CC-BY 4.0)
- Map data © [OpenStreetMap](https://www.openstreetmap.org/copyright)
  contributors (ODbL 1.0)
- Copernicus DEM © DLR e.V. and Airbus Defence and Space GmbH, provided under
  COPERNICUS by the European Union and ESA

The default basemap uses the OpenStreetMap standard tile layer, which is
acceptable for development with attribution but **not** for a public
deployment. Point `NEXT_PUBLIC_BASEMAP_TILE_URL` at your own tile server or a
commercial provider first.
