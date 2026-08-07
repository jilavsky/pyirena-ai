# 04 — Reference Library & Memory Architecture

**Status:** Draft — for review
**Purpose:** Define *how to capture, structure, and eventually serve* the two
example libraries that will drive a classification-first (feature-first) fitting
agent — the **artifact/quality library** and the **fit-exemplar library** — so
that the data collected now is directly usable later, without a foundational
mistake.

This plan is deliberately about **data preparation and layout**, not about
building the classifier. The classifier design lives in the companion note on
layered triage. The one thing that must be right *now* is the on-disk contract
(the sidecar schema) and the provenance we capture at labeling time. Everything
else is regenerable from that.

---

## 0. The core idea (read this first)

The problem we are solving: an agent that is *told* how to fit one curve applies
those rules to the next curve, where they are wrong. The fix is to give the agent
**worked examples to match against**, not rules to apply — and to let the physics
(fit residuals) do the final discrimination.

That turns the whole thing into a **retrieval problem**:

1. For an unknown curve, compute a model-agnostic **fingerprint** (slopes,
   knees, Porod exponent, oscillations, structure-factor peak, artifact flags).
2. Retrieve the *k* most similar **exemplars** from the library.
3. Inject those few exemplars (curve thumbnails + their labels + the expert's
   rationale) into the agent context as few-shot examples.
4. The agent proposes the top 1–3 candidate tools/configs and lets fit quality
   choose.

"It won't fit in a Markdown file" is exactly right — and it doesn't need to.
Only the *k* retrieved exemplars (typically 3–8) enter the context per query.
The full library lives on disk and is reached through an index. This is
retrieval-augmented generation (RAG) over your own 25 years of fits.

**Consequence for data prep:** every example must carry (a) enough to *retrieve*
it (the fingerprint + provenance) and (b) enough to *teach from it once retrieved*
(the label + the expert rationale). Get those two right and the backend choice
(vector DB, SQLite, whatever) becomes a swappable, rebuildable detail.

---

## 1. Three libraries, one schema

We collect three *kinds* of example, but they all share **one sidecar schema**
(discriminated by a `kind` field). Using one schema means one validator, one
index builder, one retrieval path.

| kind | what it is | primary use |
|------|------------|-------------|
| `artifact` | a curve (or curve region) with a known measurement/reduction defect, annotated with *what*, *where*, *why*, and *what to do* | Layer 0 — teach the agent to mask/flag, and to *not* model artifacts |
| `fit_exemplar` | a real dataset + the tool/config you actually chose + the fitted parameters + why | Layer 2 — route an unknown curve to the right tool with a warm start |
| `canonical_template` | a clean, often simulated, textbook case of one model (sphere, single Unified level, 2-level, broad size-dist + background, …) | the "anchor" points of the map; nearest-template matching |

You will realistically build these in this order of effort: `canonical_template`
(cheap, you can simulate them from Irena forward models), `fit_exemplar` (bulk
auto-harvest from your archive, then curate), `artifact` (hand-picked, slow, but
each one is very high value because it encodes knowledge the agent cannot derive).

---

## 2. On-disk layout

One **entry = one folder**, so the curve, the sidecar, and any thumbnails travel
together and are trivially added/removed/versioned. Raw data stays out of git
(large, and often already lives in NXcanSAS elsewhere); the entry stores a
*reduced* copy small enough to keep.

```
reference-library/
  entries/
    <entry_id>/
      entry.json          # the sidecar — THE contract (schema below)
      curve.csv           # reduced I(Q): columns q, I, dI, dQ  (physical units)
      thumb.png           # optional log-log thumbnail for human/agent eyeballing
  schema/
    entry.schema.json     # JSON Schema, versioned
  README.md
  MANIFEST.parquet        # DERIVED — rebuilt from entries/, never hand-edited
  index/                  # DERIVED — vector index, rebuilt from entries/
```

`<entry_id>` = a stable content hash of the reduced curve + source path (so the
same measurement never gets two IDs). Never reuse an ID for different data.

**What is source-of-truth vs. derived:**

- **Source of truth (back this up, version it):** `entries/**/entry.json` and
  `entries/**/curve.csv`. Hand-authored. Nothing else.
- **Derived (regenerable, disposable, `.gitignore`-able):**
  `MANIFEST.parquet`, `index/`, any embeddings, any distilled prompt cards.
  A single `build_indices.py` recreates all of it from `entries/`.

This separation is the safety net: if you later change embedding models, add a
descriptor, or switch vector stores, you rebuild the derived layer and lose
nothing. The only irreversible act is failing to capture something at labeling
time — see §5 for that list.

---

## 3. The sidecar schema (`entry.json`)

Full JSON Schema ships alongside this doc (`reference-library/schema/entry.schema.json`)
with two worked examples. The shape, annotated:

```jsonc
{
  "schema_version": "1.0.0",
  "entry_id": "sha1:9f3c…",
  "kind": "fit_exemplar",               // artifact | fit_exemplar | canonical_template

  // ── PROVENANCE ── who/what/where. Cheap to record now, impossible to
  //    reconstruct later. Instrument config is the #1 transferability lever.
  "provenance": {
    "source_file": "/archive/2019/APS_9ID/steelX_00123.h5",
    "source_nxentry": "sasentry1/sasdata1",
    "instrument": "APS 9ID USAXS (Bonse-Hart)",
    "geometry": "slit_smeared",          // slit_smeared | desmeared | pinhole_2d
    "q_units": "1/angstrom",
    "sample": "precipitates in ferritic steel, aged 500C/100h",
    "contrast_sld_diff": 6.1e-6,         // if known, else null
    "date": "2019-06-14",
    "operator": "JI"
  },

  // ── DATA ── pointer + envelope. Enough to filter without opening the curve.
  "data": {
    "curve_file": "curve.csv",
    "q_min": 1.0e-4, "q_max": 0.3,
    "n_points": 220,
    "decades_q": 3.5,
    "smeared": true,
    "has_dQ": true
  },

  // ── DESCRIPTORS ── the model-agnostic fingerprint. VERSIONED and REGENERABLE
  //    (produced by detect_features + extensions). Stored so the index can be
  //    built without recomputing, but never hand-tuned as if permanent.
  "descriptors": {
    "descriptor_version": "1.0.0",
    "power_law_segments": [
      {"q_lo": 1e-4, "q_hi": 3e-4, "slope": -3.9, "slope_sigma": 0.1, "kind": "porod_surface"},
      {"q_lo": 3e-4, "q_hi": 0.02, "slope": -2.1, "slope_sigma": 0.2, "kind": "mass_fractal"}
    ],
    "guinier_knees": [{"q": 0.004, "Rg_est": 90.0}],
    "n_knees": 1,
    "porod_exponent_highq": -4.0,
    "lowq_behavior": "power_law_upturn",   // plateau | power_law_upturn | knee
    "highq_behavior": "flat_background",    // flat_background | porod | rising
    "oscillations": false,                  // monodisperse form-factor ringing
    "structure_factor_peak": {"present": false, "q": null},
    "dynamic_range_decades": 6.2,
    "recommended_nlevels": 2
  },

  // ── QUALITY / ARTIFACTS ── the by-eye knowledge. Present on EVERY entry
  //    (empty list if clean). For kind=artifact this is the payload.
  "quality": {
    "trusted_q_range": {"q_min": 2e-4, "q_max": 0.25},
    "artifacts": [
      {
        "q_lo": 0.25, "q_hi": 0.3,
        "type": "poor_statistics",         // controlled vocab — see schema enum
        "severity": "high",                // low | medium | high
        "why": "counting-limited high-Q tail, dominated by noise below flat bkg",
        "action": "trim"                   // trim | mask | keep_with_caution | desmear_issue
      }
    ]
  },

  // ── LABEL ── only for fit_exemplar / canonical_template. The 'answer'.
  "label": {
    "tool": "unified_fit",                 // unified_fit | size_distribution
    "config": {
      "nlevels": 2,
      "background": "flat",                // flat | power_law | complex | none
      "levels": [
        {"Rg": 90, "G": 1200, "P": 4.0, "B": 3e-9, "correlations": false},
        {"Rg": 900, "G": null, "P": 2.1, "B": 5e-6}   // large-scale power law
      ]
    },
    "fit_quality": {"chi2_reduced": 1.8, "notes": "residuals flat except trimmed tail"},
    "fit_q_range": {"q_min": 2e-4, "q_max": 0.25}
  },

  // ── RATIONALE ── the transferable expert voice. This is what makes a
  //    retrieved exemplar *teach* rather than just match.
  "rationale": {
    "decision_cues": [
      "single Guinier knee at 0.004, no oscillation -> one discrete population",
      "Porod -4 high-Q -> sharp interfaces, surface scattering",
      "low-Q -2.1 upturn -> large-scale mass-fractal aggregation, model as power-law level"
    ],
    "expert_notes": "Classic two-level: precipitate population on an aggregate upturn. Did NOT use size-distribution because the knee is discrete, not a broad continuum.",
    "alternatives_considered": ["size_distribution (rejected: knee too sharp)"]
  },

  // ── GOVERNANCE ── trust + splitting + housekeeping.
  "meta": {
    "label_confidence": "high",           // high | medium | low
    "labeled_by": "JI",
    "labeled_date": "2026-08-01",
    "split": "train",                     // train | val | holdout
    "tags": ["steel", "precipitates", "USAXS", "two-level"]
  }
}
```

Design notes:

- **`descriptors` is regenerable, everything in `provenance`/`quality`/`rationale`
  is not.** If you are ever unsure whether to record something, ask "could a
  script recompute this from the curve later?" If yes, it's optional now. If no
  (why you trusted a q-range, why you rejected size-dist), it must be captured
  at labeling time or it's gone.
- **Controlled vocabularies** (`artifact.type`, `geometry`, `lowq_behavior`,
  `tool`, `background`) live as enums in the schema. Keep them small and grow
  them deliberately — this is what makes cross-entry queries and clustering work.
  Free text goes in `rationale`, never in a field you'll want to filter on.
- **`label` is null for `artifact` entries; `quality.artifacts` is the payload
  there.** One schema, discriminated by `kind`.

---

## 4. The memory architecture (how it gets "racked in")

Three tiers. Only the first is precious.

**Tier 1 — Corpus (source of truth).** The `entries/` folder. Flat files, git or
git-LFS or a plain backed-up directory. This is the thing you are building over
the next weeks/months. Nothing reads it directly at query time.

**Tier 2 — Derived indices (rebuilt by script, never hand-edited).**
- `MANIFEST.parquet`: one row per entry, all scalar descriptors + provenance
  flattened. This powers **rule/filter retrieval** ("give me slit-smeared
  entries with one knee, Porod −4, flat high-Q") and clustering. A DataFrame or
  a SQLite table — both fine; parquet is zero-setup.
- `index/`: a **vector index** of a fixed-length embedding per entry, for
  **similarity retrieval** ("curves that look like *this* one"). Start with an
  embedding built directly from the descriptor vector (normalized slopes, knee
  positions, flags) — no ML training needed, fully interpretable. Later you can
  swap in a learned embedding (a small 1-D CNN on log-log I(Q), à la the Monge
  representation-learning paper) without touching Tiers 1 or 3. Store with
  FAISS, `sqlite-vec`, or Chroma — all rebuildable, so the choice isn't binding.

**Tier 3 — Distilled prompt assets (small, curated, in-repo).** The few-shot
"pattern cards" that actually enter the agent context. Generated by clustering
the corpus (Tier 2) and writing one compact card per cluster — this is exactly
the format your existing `skills/saxs_visual_patterns.md` wants to be, but
*derived from data* instead of hand-written. A card = a canonical thumbnail +
the descriptor signature + the routing decision + 1–2 lines of rationale.

**Query-time flow (what the agent actually does):**

```
unknown curve
  -> detect_features() → descriptor fingerprint      (you already have this tool)
  -> filter MANIFEST by hard descriptors             (Tier 2, cheap, narrows field)
  -> vector search for k nearest exemplars           (Tier 2)
  -> inject those k entries' thumbnails+labels+rationale into context  (Tier 3-style)
  -> agent proposes top 1–3 tools/configs, warm-started from their labels
  -> fit each, let residuals decide                  (physics is the arbiter)
```

The agent never loads the corpus. This is why size is a non-issue: 10,000
entries on disk, 5 in context.

---

## 5. What MUST be correct now (the no-regrets checklist)

Everything derived can be rebuilt. These cannot, so nail them from entry #1:

1. **Freeze the schema version.** `schema_version` on every entry. When it
   changes, write a migration; never silently reinterpret old files.
2. **Stable, content-based `entry_id`.** No duplicates, no reuse.
3. **Reduced curve in physical units** with `q_units`, `smeared` flag, and `dQ`
   if you have it. A curve you can't unambiguously interpret later is dead weight.
4. **Instrument `geometry` / configuration.** This is the single biggest driver
   of the "works here, fails there" problem (the Monge et al. transferability
   finding). Slit-smeared vs desmeared vs pinhole must be on every entry so you
   can *train and test across configs on purpose*.
5. **Artifact annotations and `trusted_q_range` captured at labeling time.**
   Your instant by-eye rejection of bad points is the knowledge that is
   otherwise unrecoverable. Record *where*, *what type*, *why*, *what you did*.
6. **`rationale.decision_cues` + `alternatives_considered`.** "Why not the other
   tool" is often more valuable for routing than "why this tool."
7. **`label_confidence` and `split`.** Mark your unsure labels honestly, and
   assign holdout by *whole sample-system / instrument*, not random rows, so the
   eventual transferability test is real.

If all seven are present, any modeling mistake later is cheap to fix.

---

## 6. Harvesting from the existing archive (cheap bulk, then curate)

You have thousands of saved fits. Don't hand-label them — script a **first pass**
that auto-emits sidecars, then hand-curate a curated subset.

**Pass A — automatic (covers `fit_exemplar` in bulk).** For each NXcanSAS file
with a saved fit, a script uses the existing read tools to populate everything
that is machine-derivable:
- `pyirena_read_reduced_data` → `curve.csv`, `data` block.
- `pyirena_read_unified_fit` / `pyirena_read_size_distribution` /
  `pyirena_read_simple_fit` → `label.tool`, `label.config`, `label.fit_quality`,
  `label.fit_q_range`. **The saved fit *is* the label** — the tool you chose and
  the q-range you trusted are already recorded in the file. This is the gold.
- `detect_features` → `descriptors`.
- `pyirena_read_metadata` → `provenance` (instrument, date, sample where present).

Pass A gives you a large, weakly-labeled corpus for free. Mark these
`label_confidence: "medium"` and `labeled_by: "auto"`.

**Pass B — human curation (the high-value layer).** Walk a *representative* few
hundred (spanning your model types and instrument configs), and add what the
script cannot: `rationale`, `quality.artifacts`, corrected `trusted_q_range`,
`label_confidence: "high"`. Promote the best, cleanest ones to
`canonical_template`. This is where your 25 years actually get encoded.

**Pass C — artifacts (ongoing, opportunistic).** Whenever you spot a good
teaching artifact in daily work, drop a `kind: "artifact"` entry. These are rare
and slow but each is worth many ordinary exemplars.

A stub `harvest.py` should live in `reference-library/` (Phase 2 below); the
schema and examples shipping now are what you validate it against.

---

## 7. Phased plan

**Phase 0 — freeze the contract (this note + shipped files).** Schema + two
worked examples + folder layout. *Done when you agree the schema captures
everything in §5.* ← we are here.

**Phase 1 — descriptor definition.** Pin `descriptor_version 1.0.0`: the exact
fingerprint fields and how each is computed (mostly = current `detect_features`
output + Porod exponent, oscillation flag, structure-factor-peak flag,
dynamic-range/decade coverage). Write it down as a spec so Pass A is
deterministic and reproducible.

**Phase 2 — harvester.** `harvest.py` implementing Pass A over a sample folder;
validate every emitted `entry.json` against the schema in CI.

**Phase 3 — index builder.** `build_indices.py` → `MANIFEST.parquet` + a
descriptor-vector index. Add a `retrieve(curve) -> k entries` function. No ML yet.

**Phase 4 — curation sprint.** Pass B on a few hundred; cluster; auto-generate
the distilled pattern cards (Tier 3) and diff them against the current
hand-written `saxs_visual_patterns.md`.

**Phase 5 — wire into the agent.** Replace/augment the static strategy rules with
retrieval: fingerprint → retrieve → inject exemplars → propose top-N → fit → let
residuals decide. Hold out whole configs to measure transferability honestly.

**Phase 6 (optional) — learned embedding.** Swap the descriptor-vector embedding
for a trained representation (1-D CNN on log-log I(Q)). Tiers 1 and 3 unchanged.

---

## 8. Definition of done for the data-prep phase

You are safe to stop worrying about "did I set it up wrong" when:

- [ ] The schema validates, versioned, with enums for every filterable field.
- [ ] Two example entries (one `artifact`, one `fit_exemplar`) validate against it.
- [ ] A single entry round-trips: curve + sidecar + thumbnail in one folder,
      reconstructable with no external context.
- [ ] `provenance.geometry` and `quality.trusted_q_range` are mandatory (schema-
      enforced) so no entry can be created without them.
- [ ] You can point `harvest.py` at one archive folder and get valid entries out.
- [ ] Holdout is assignable by sample-system / instrument, not by random row.

Once those hold, the corpus can grow to any size and every derived layer
(indices, embeddings, prompt cards, even the classifier) is rebuildable on top
of it. The only irreplaceable asset is the annotated corpus — and this layout
makes capturing it a mechanical, low-risk activity you can do in spare minutes
between other work.

---

## Appendix — relation to prior art

- **Monge et al. 2024 (Acta Cryst A), model selection by representation
  learning:** their key negative result — classification rules transfer poorly
  across instrument configurations — is why `provenance.geometry` is mandatory
  and why holdout is by config. Their positive result (train across configs)
  is a Tier-2/Phase-6 concern, not a data-prep concern.
- **Multi-task classification + parameter regression (Digital Discovery 2024):**
  motivates storing both the tool (`label.tool`) and a warm-start config
  (`label.config`) — retrieval returns both.
- **Autonomous experimentation / unsupervised clustering (Yager, NSLS-II):**
  the Tier-3 pattern-card generation is descriptor-space clustering of your own
  corpus.
- **CREASE (Jayaraman):** the fallback philosophy for curves no library model
  matches — a later extension, out of scope here.
