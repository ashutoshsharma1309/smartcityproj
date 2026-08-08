# Development roadmap

Phase 1 is complete. Each phase below ends in something runnable and
demonstrable; none is finished while a capability it claims returns invented
data.

---

## Phase 1 — Foundation ✅

Repository, containerised PostGIS and Redis, FastAPI skeleton with health and
versioned routes, provenance schema and migrations, module registry, test
suite, and the Next.js + MapLibre shell.

**Done when:** the stack starts, migrations apply, tests pass, and the
dashboard renders live backend state. ✅

---

## Phase 2 — Real data in the warehouse

Fill the tables. Nothing downstream is meaningful until this is real.

1. **Overpass ingestion** — ward boundaries → `zones`, roads → `road_segments`.
   Rate-limited with backoff; Overpass will refuse an impolite client.
2. **Open-Meteo ingestion** — historical archive backfill (several years) plus a
   scheduled forecast poll. Forecast rows stored with `is_forecast = true` so
   they never leak into training.
3. **DEM ingestion and terrain derivation** — sample Copernicus GLO-30 per zone;
   fill `mean_elevation_m`, `mean_slope_deg`, `depression_area_fraction`.
4. **Validation service** — range checks, geometry validity, duplicate
   detection. Rejections counted per reason on the run record.
5. **Scheduled jobs** — Redis-brokered periodic ingestion.

**Resolve the label gap.** The blocker for Phase 3 is historical waterlogging
incidents (see `known_gaps` in `data/metadata/data_sources.json`). Options, in
order of preference: a formal data request to the municipal corporation; weak
labels derived from geotagged reports and stored with `origin = 'derived'`; a
licensed academic inundation dataset. **If none succeeds, Phase 3 does not
proceed to a probability** — the honest outcome is an unsupervised
susceptibility index, clearly labelled as such, not a fabricated risk score.

**Done when:** `/api/v1/catalog/summary` reports non-zero counts, the map draws
real ward polygons, and every row traces to a registered source.

---

## Phase 3 — Risk prediction

1. **Feature pipeline** — implement `ml/features/specification.py` against the
   warehouse; one code path shared by training and inference.
2. **Baseline first** — a rainfall-threshold rule. The gradient-boosted model
   must beat it, or it is not earning its complexity.
3. **LightGBM classifier** — time-based splits, never random: random splits leak
   future rainfall into the training set and produce a flattering, false score.
4. **Calibration** — isotonic or Platt scaling. An uncalibrated "70%" that is
   really 30% is worse than no number, because it will be acted on.
5. **SHAP attributions** — populate `top_contributions` from the model.
6. **Missing-input handling** — populate `missing_inputs`; widen `confidence`
   where inputs are sparse.
7. **Wire up `PredictionService`** — replace the stub; the 501s become real
   responses.

**Done when:** `/api/v1/risk/surface` returns calibrated probabilities that beat
the baseline on a held-out period, and every prediction names its drivers.

---

## Phase 4 — Impact and recommendations

1. **Road graph** — NetworkX graph from `road_segments`, cached in Redis.
2. **Impact analysis** — intersect at-risk zones with roads; identify critical
   links whose removal disconnects the graph, and zones left with no access.
3. **Recommendation rules** — declarative rule set (pump deployment, traffic
   diversion, pre-positioning), each action carrying the rule that fired.
4. **Map layers** — risk choropleth and affected roads, with an explicit legend
   and a visible "last computed" timestamp.

**Done when:** a high-risk forecast produces a named list of affected roads and
auditable recommended actions.

---

## Phase 5 — Explanation and real-time

1. **Concrete LLM provider** — register one in `PROVIDER_FACTORIES`; the rest of
   the codebase is unaffected.
2. **Grounding tests** — assert generated text contains no number absent from
   the prompt. This is the guard that keeps the LLM honest under model changes.
3. **Alert service** — threshold crossings become events.
4. **WebSocket push** — Redis pub/sub → FastAPI socket → live dashboard.
5. **Simulation layer** — replay historical storms for demos. Served through
   separate, clearly-marked endpoints; simulated rows carry
   `origin = 'simulated'` and the UI badges them.

**Done when:** an operator sees a live risk change, a plain-language briefing,
and can replay a past storm without any chance of mistaking it for live data.

---

## Phase 6 — Evaluation and hardening

1. **Backtesting harness** — replay historical events; report precision, recall
   and lead time, not just AUC.
2. **Calibration and drift monitoring** — on live feature distributions.
3. **Model registry** — versioned artefacts; every stored prediction records the
   version that produced it.
4. **Authentication** — API keys or OIDC for municipal users.
5. **Production containers** — multi-stage frontend build on `next start`;
   non-root users; pinned digests.
6. **CI** — lint, tests and migration checks on every push.

---

## Extending beyond flooding

The pipeline shape — ingest → validate → geospatial → features → predict →
impact → recommend → explain — is not flood-specific. A second hazard reuses
the provenance schema, zone geometry, road graph, impact engine and LLM layer;
what changes is the feature set and the model. Air quality and heat-island risk
are the natural next problems, both with open data and the same zone geometry.

The one thing to guard when generalising: **do not let a second hazard ship
with a fabricated label set** because the first one made the pipeline look easy.
Every hazard needs its own honest answer to "what is the ground truth?"
