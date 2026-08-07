# Reference Library

Worked examples that drive a **classification-first** (feature-first) fitting
agent. Design and rationale: [`../04-reference-library-and-memory.md`](../04-reference-library-and-memory.md).

## Layout

```
reference-library/
  entries/<entry_id>/
    entry.json      # the sidecar — the contract (validated against schema/)
    curve.csv       # reduced I(Q): columns q, I, dI, dQ (physical units)
    thumb.png       # optional log-log thumbnail
  schema/
    entry.schema.json
  examples/
    fit_exemplar.example.json
    artifact.example.json
  MANIFEST.parquet  # DERIVED — rebuilt from entries/, git-ignored
  index/            # DERIVED — vector index, git-ignored
```

## The one rule

**`entries/**/entry.json` + `curve.csv` are source of truth. Everything else is
derived and rebuildable.** Get the sidecar schema and the labeling-time
annotations (instrument geometry, trusted Q-range, artifact notes, rationale)
right; do not hand-edit anything derived.

## Entry kinds

- `artifact` — a defect region annotated with what/where/why/action. `label` is null.
- `fit_exemplar` — a real dataset + the tool/config you chose + why.
- `canonical_template` — a clean/simulated textbook case anchoring one model.

## Validate an entry

```bash
pip install jsonschema
python -c "import json,jsonschema; \
  s=json.load(open('schema/entry.schema.json')); \
  d=json.load(open('examples/fit_exemplar.example.json')); \
  jsonschema.validate(d,s); print('ok')"
```

## Status

Phase 0 (freeze the contract). `harvest.py` (auto-populate sidecars from the
NXcanSAS archive) and `build_indices.py` come in Phases 2–3 — see the plan.
