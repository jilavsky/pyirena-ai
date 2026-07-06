# Size Distribution — Parameter Reference and Interpretation Guide

Reference for pyirena's particle size-distribution inversion. The workflow and
hard rules live in the strategy file — this file covers what each setting means,
how to choose it, and how to read the result.

## What the model does

The inversion recovers **P(r)**, the volume-weighted distribution of particle
radii, from the background-subtracted I(Q):

```
I(Q) − background  ≈  contrast · ∫ P(r) · |F(Q, r)|² · V(r) dr
```

where `F` is the sphere (or spheroid) form factor. It answers "what mix of
particle sizes produces this curve?" for a **single dilute population**. It is
the wrong tool for hierarchical / multi-level structure — use Unified Fit there.

## Suitability — read `suggest_sizes_setup` first

`suggest_sizes_setup(session_id)` inspects the data and returns:
- `suitable` — whether the curve looks like one viable size-distribution
  candidate.
- `recommended` — `r_min`, `r_max`, `inversion_q_min/max`,
  `power_law_q_min/max`, `background_q_min/max` (any window may be `null`).
- `warnings` — e.g. *no Guinier knee* (no size scale), *multiple populations*
  (use Unified Fit), *limited Q dynamic range*.

Treat these as the authoritative starting point. If `suitable` is false, prefer
Unified Fit over forcing the inversion.

## Inversion methods

Set with `select_sizes_model(method=…)` or `set_method(...)`:

- **`maxent`** (default) — Maximum Entropy. Smoothest distribution consistent
  with the data; the safest, most robust choice. Tunables:
  `maxent_sky_background`, `maxent_max_iter`.
- **`regularization`** — Tikhonov-style. Good alternative; `regularization_evalue`,
  `regularization_min_ratio` control smoothness.
- **`tnnls`** — strict non-negativity, no smoothing; can give spiky P(r).
- **`montecarlo`** (McSAS) — stochastic, slower; use only when asked. Vary by
  `montecarlo_n_repetitions`, `montecarlo_convergence`, `montecarlo_max_iter`.

## Shape & contrast — `set_shape`

- `shape`: `"sphere"` (default) or `"spheroid"` (needs `aspect_ratio`).
- `contrast`: the scattering contrast (Δρ)² in 10²⁰ cm⁻⁴. It sets the **absolute
  scale** of the recovered volume fraction.
  - **Unknown contrast → use `1.0`** and treat `volume_fraction` as *relative*,
    not absolute. Always state this caveat in the report.
  - A correct contrast makes `volume_fraction` a true absolute volume fraction.

## Size grid — `set_size_grid`

- `r_min`, `r_max`: radius range in **Å**. Heuristic: `r ≈ π/Q` over the
  inversion Q-range (so small Q ⇒ large r). Start from the recommended values.
- `n_bins`: 100–300 is typical; 200 is a good default.
- `log_spacing=True`: recommended for wide size ranges.
- **The grid must bracket the real sizes.** If the recovered peak sits at an
  edge, the grid is clipping the distribution — widen it and refit.

## Error handling — `set_error_handling`

Two mutually exclusive modes:
- **Error scaling** (default): use file σ × `error_scale` (1.0 = unchanged).
  Raise it when the error bars are too small and the inversion chases noise
  (jagged P(r)).
- **Fractional error**: `fractional_error=True` ignores file σ and uses
  σ = |I| × `fractional_error_value` (e.g. 0.03 = 3%). Use when the file
  uncertainties are unreliable or missing.

## Complex background

Subtracted before inversion: `power_law_B · q^(-power_law_P) + background`.
Set the two terms either directly (`set_background`) or by fitting each over its
own Q-window:
- `fit_power_law_background(q_min, q_max, fit_B, fit_P)` — the low-Q steep-slope
  region (large-scale scattering / upturn you don't want in the inversion).
- `fit_flat_background(q_min, q_max)` — the high-Q flat tail (incoherent /
  constant background). Run after the power-law fit when both are present.

These windows use the **full data Q**, independent of the inversion Q-range.
Always confirm with `get_background_preview_image` before inverting — a wrong
background is the most common cause of a bad or distorted P(r).

## Reading the results

`run_sizes_fit` / `get_sizes_results` return:
- **`volume_fraction`** — ∫P(r)dr. Absolute only if `contrast` is real;
  otherwise relative.
- **`rg`** — the volume-weighted radius of gyration of the distribution.
- **`peak_r`** — radius at the maximum of P(r). **If `peak_r` is at `r_min` or
  `r_max`, the grid is too narrow — widen and refit.**
- **`chi_squared`** — subject to the usual SAXS σ-misscale caveat; do not chase a
  specific value. Judge from the image instead.
- `n_iterations`, `n_data`.

`get_sizes_distribution` returns the `r_grid` and `distribution` arrays (plus
`distribution_std` when the method provides it).

## Judging the fit visually

`get_sizes_fit_image` is the primary quality tool. A good fit:
- model + background tracks the data across the inversion window, and
- P(r) is a smooth, physically plausible peak (or few peaks), not piled at a
  grid edge and not a forest of noise spikes.

Symptoms → fixes:
- **Jagged / spiky P(r)** → raise `error_scale` or use fractional errors; prefer
  `maxent` over `tnnls`.
- **Peak at a grid edge** → widen `set_size_grid`.
- **Model misses the data shape** → re-check the complex background; if still bad
  with a clean background, the data may be multi-population → Unified Fit.
