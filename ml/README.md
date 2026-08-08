# ML pipeline

Offline feature building, training and evaluation. Runs as batch jobs, not
inside the API process.

## Why this is a separate environment

The API serves precomputed geometry from PostGIS and, from Phase 3, loads a
single small model artefact. It never trains and never needs GeoPandas,
rasterio or LightGBM's training runtime. Keeping those out of
`backend/pyproject.toml` keeps the API image small and its cold start fast.

```bash
uv venv --python 3.12 ml/.venv
uv pip install --python ml/.venv -r ml/requirements.txt
```

## Layout

| Path          | Purpose                                                        |
| ------------- | -------------------------------------------------------------- |
| `data/`       | Dataset loaders reading from PostGIS and the public APIs.       |
| `features/`   | Feature construction. `specification.py` is the shared contract. |
| `models/`     | Trained artefacts (gitignored — reproduced by `training/`).     |
| `training/`   | Training entrypoints and hyperparameter configuration.          |
| `inference/`  | Batch scoring; writes risk surfaces the API reads.              |
| `evaluation/` | Backtests against historical incidents, calibration, drift.     |

## Model choice

LightGBM, not a neural network and not an LLM:

- The feature set is small, tabular and mostly monotonic — gradient-boosted
  trees are the right tool and are hard to beat here.
- It trains in seconds on a CPU-only laptop, which is a hard constraint for
  this project.
- SHAP gives exact per-prediction attributions, so the "why" shown in the UI
  comes from the model itself rather than a plausible-sounding narrative.
- Native NaN handling means a genuinely missing input stays missing instead of
  being imputed into an invented value.

## Status

`features/specification.py` declares the full feature contract. Two features
and — more importantly — the training label are marked unavailable, because no
data source supplies them yet:

- `tide_height_m`
- `drain_capacity_index`
- the label `waterlogging_occurred`, from historical incident records

Those gaps are recorded in `data/metadata/data_sources.json` under
`known_gaps`. Until the label gap is closed no model can be trained, and the
API correctly returns 501 for every risk endpoint rather than a number.
