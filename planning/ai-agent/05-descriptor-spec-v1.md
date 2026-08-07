# 05 — Descriptor Specification `descriptor_version 1.0.0`

**Status:** Draft — for review
**Purpose:** Pin the exact, deterministic definition of the model-agnostic
**fingerprint** stored in every library entry's `descriptors` block
(see [`04-reference-library-and-memory.md`](04-reference-library-and-memory.md)
§3). This is the Phase 1 blocker: once frozen, the harvester (Phase 2) and the
retrieval index (Phase 3) are reproducible.

A descriptor is admissible in v1.0.0 only if it is **(a) computable from I(Q),
dI, dQ alone, (b) deterministic** (same curve → same value), and **(c)
instrument-robust or explicitly carrying the instrument context it needs.**
Anything requiring a model fit or human judgment is *not* a descriptor — it
belongs in `label`, `quality`, or `rationale`.

Most of this reuses the existing `detect_features` output; the spec names which
fields come straight from it and which are new derived quantities, so the
harvester is a thin, auditable wrapper.

---

## 0. The smearing rule (read first — this is a foundational decision)

Slit-smeared USAXS slopes are **not** the same numbers as desmeared/pinhole
slopes: slit smearing reduces a power-law slope magnitude by ~1 (a true Porod
−4 appears as ≈ −3), and it rounds Guinier knees. If we store "slope = −3"
without context, an entry from slit-smeared data will falsely match a genuine
mass-fractal −3 from pinhole data. That is exactly the cross-config mismatch we
are trying to avoid.

**Decision for v1.0.0:**

1. All descriptor geometric quantities (`slope`, `q`, `Rg_est`, exponents) are
   computed **as-measured on the stored curve**, and the entry's
   `provenance.geometry` records whether that curve is `slit_smeared`,
   `desmeared`, or `pinhole_2d`.
2. The harvester additionally stores, for each power-law segment, an
   **`slope_desmeared_equiv`** = `slope − 1.0` when `geometry == "slit_smeared"`,
   else `= slope`. Retrieval and clustering key on `slope_desmeared_equiv`, so
   entries compare on physically equivalent footing regardless of geometry.
   *(This field is added to the schema when we freeze; noted here so we don't
   forget the correction exists.)*
3. Never mix as-measured and corrected values in the same comparison. Retrieval
   uses corrected; human-facing thumbnails show as-measured.

If you disagree and would rather **desmear everything before descriptor
computation**, that is the alternative — cleaner slopes, but you lose the raw
curve's fidelity and inherit desmearing artifacts into the fingerprint. My
recommendation is store-as-measured + carry the correction, because it keeps the
raw curve authoritative and the correction transparent.

---

## 1. Field-by-field definition

Each field below lists: **source** (`detect_features` = reuse; `derived` = new
computation in the harvester), the computation, and units.

### 1.1 `descriptor_version`
Literal `"1.0.0"`. Bump policy in §3.

### 1.2 `power_law_segments[]`
**Source:** `detect_features.segments` (reuse) + `derived` classification.
Each contiguous log-log region well-described by a single slope.
- `q_lo`, `q_hi` — segment bounds [q_units].
- `slope` — least-squares slope of `log10(I)` vs `log10(Q)` over the segment, as
  measured. Dimensionless.
- `slope_sigma` — standard error of that slope. If `detect_features` does not
  return it, the harvester recomputes via the covariance of the linear fit.
- `slope_desmeared_equiv` — §0 rule.
- `kind` — `derived`, assigned from `slope_desmeared_equiv` by the fixed table:

  | slope_desmeared_equiv range | kind | physical reading |
  |---|---|---|
  | slope ≤ −3.9 (≈ −4) | `porod_surface` | sharp, smooth interfaces |
  | −3.9 < slope ≤ −3.0 | `surface_fractal` | rough interface, Ds = 6 + slope |
  | −3.0 < slope ≤ −1.0 | `mass_fractal` | Df = −slope |
  | −1.0 < slope < 0 | `diffuse` | weak/short-range, or bad range |
  | slope ≥ 0 or ambiguous | `other` | flag for human review |

  Boundaries are inclusive at the more-negative end. Segments straddling a
  boundary within `slope_sigma` get `other` and are surfaced for curation.

### 1.3 `guinier_knees[]`
**Source:** `detect_features.guinier_knees` + `recommended_guinier_windows`.
- `q` — knee position [q_units], where the curve rolls from a plateau/shallow
  region into a steeper power law.
- `Rg_est` — quick estimate, **not a fit**: `Rg_est = sqrt(3)/q_knee` (the
  standard knee↔Rg relation), or, when a recommended Guinier window exists, the
  slope of `ln(I)` vs `Q^2` over that window (`Rg = sqrt(-3·slope)`). Record
  which method in `Rg_est_method` (`knee_rule` | `guinier_window`). [length,
  1/q_units].

### 1.4 `n_knees`
**Source:** `derived` = `len(guinier_knees)`. Integer ≥ 0. Primary coarse router
(0 → likely power-law/fractal or broad size-dist; 1 → single population; ≥2 →
hierarchical / Unified multi-level).

### 1.5 `porod_exponent_highq`
**Source:** `derived`. Slope over the last decade of the **trusted** range
(`quality.trusted_q_range.q_max` down one decade), before the flat background
dominates. Uses `slope_desmeared_equiv` convention. Null if <½ decade of clean
high-Q signal exists above background.

### 1.6 `lowq_behavior`
**Source:** `derived` from the lowest-q segment. Enum:
- `plateau` — |slope| < 0.3 at the lowest q (finite-size, bounded).
- `power_law_upturn` — slope ≤ −0.3 continuing to q_min (aggregation / large
  scale; usually model as a power-law level or size-dist upturn).
- `knee` — a Guinier knee sits within the lowest 20% of the q-range (largest
  population resolved).

### 1.7 `highq_behavior`
**Source:** `derived` + `detect_features.background_q_min`. Enum:
- `flat_background` — I(Q) flattens to a constant above `background_q_min`.
- `porod` — still falling with slope ≈ −4 at q_max (background not reached; more
  q needed or incoherent bkg negligible).
- `rising` — I(Q) rises at high q (bad subtraction / fluorescence — usually an
  artifact, cross-check `quality`).

### 1.8 `oscillations`
**Source:** `derived`. Boolean: are there ≥1 statistically significant local
minima in the form-factor sense (monodisperse ringing)? Heuristic: fit a smooth
monotone power-law-plus-knee envelope; flag `true` if the residual shows ≥1
dip-and-recover exceeding `3·dI` over ≥3 adjacent points, at a q consistent with
a form-factor minimum (not a single spike → that's a `cosmic_spike` artifact).
Because ringing is easy to confuse with a desmearing artifact (see the artifact
example entry), the harvester sets `oscillations=true` but the curation tool
**always** asks the human to confirm sample-vs-artifact.

### 1.9 `structure_factor_peak`
**Source:** `derived`. `{present: bool, q: number|null}`. Detect a local
**maximum** in I(Q) (or in `I(Q)·Q^p` for the local power p) rising above the
smooth envelope by > `3·dI` over ≥3 points → interparticle correlation / ordering
peak. `q` = peak position or null.

### 1.10 `dynamic_range_decades`
**Source:** `derived` = `log10(I_max / I_min)` over the trusted range (I_min
taken above the noise floor / background). Dimensionless. Proxy for information
content.

### 1.11 `recommended_nlevels`
**Source:** `detect_features.recommended_nlevels` (reuse, pass-through). Integer.
Advisory only; the fit, not this number, decides.

### 1.12 Envelope fields (stored in `data`, not `descriptors`, but computed here)
- `decades_q` = `log10(q_max/q_min)`.
- `n_points`, `q_min`, `q_max`, `smeared`, `has_dQ` — read from the curve/file.

---

## 2. What is deliberately NOT a descriptor in v1.0.0

- Fitted `Rg`, `G`, `P`, `B`, size-distribution moments → these are `label`
  (they require choosing and running a model).
- Whether a feature is "real" vs "artifact" → `quality` (human judgment).
- Absolute intensity calibration / porosity / volume fraction → out of scope for
  routing; belongs in `label` or `domain_context`.
- Any 2-D / anisotropy descriptor → deferred to a future `2.0.0` (CREASE-2D
  territory).

Keeping the descriptor set small and physical is what makes the vector index
interpretable and the routing debuggable.

---

## 3. Versioning policy

- **Patch** (`1.0.x`): bug fix in a computation that does not change field
  meaning. Re-harvest optional.
- **Minor** (`1.x.0`): add a new optional descriptor field. Old entries remain
  valid; re-harvest to populate the new field when convenient.
- **Major** (`2.0.0`): change the meaning/units of an existing field, or the
  `kind` boundary table. Requires re-harvesting the whole corpus and rebuilding
  indices. Because descriptors are **derived**, a major bump is cheap: rerun the
  harvester over `entries/**/curve.csv`; no hand-labeling is lost.

`descriptor_version` is stored per entry so a mixed-version corpus is detectable
and the index builder can refuse or upgrade stale rows.

---

## 4. Reference computation order (for the harvester)

```
load curve (q, I, dI, dQ)               # from NXcanSAS reduced data
compute decades_q, dynamic_range_decades
run detect_features(curve)              # segments, knees, background_q_min, rec_nlevels
for each segment:
    slope, slope_sigma  <- linear fit log10 I vs log10 Q
    slope_desmeared_equiv <- slope (-1 if slit_smeared)
    kind <- boundary table (§1.2)
guinier_knees, n_knees, Rg_est          # §1.3-1.4
porod_exponent_highq                    # §1.5, last trusted decade
lowq_behavior, highq_behavior           # §1.6-1.7
oscillations  (flag; human confirms)    # §1.8
structure_factor_peak                   # §1.9
recommended_nlevels  <- passthrough
emit descriptors{descriptor_version="1.0.0", ...}
```

Every step is deterministic given the curve and `provenance.geometry`. That is
the whole point: two people harvesting the same NXcanSAS file must get identical
`descriptors`.

---

## Open questions for review

1. **Smearing (§0):** store-as-measured + `slope_desmeared_equiv` correction, or
   desmear-before-descriptors? (My recommendation: the former.)
2. **`kind` boundaries (§1.2):** are the surface-fractal / mass-fractal cutoffs
   where you'd draw them, or do you want a small "ambiguous band" of ±0.15
   around −3.0 that always routes to human review?
3. **Oscillation heuristic (§1.8):** is `3·dI` over ≥3 points the right
   sensitivity, or should it scale with local point density?
4. Anything in `label`/`quality` you think is actually stable/derivable enough
   to promote into `descriptors`?
