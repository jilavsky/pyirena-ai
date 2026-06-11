# Unified Fit — Parameter Reference and Residual Guide

This document is a reference supplement to the fitting workflow defined in
the strategy file. The workflow steps, ordering invariant, G validity rule,
correlation check procedure, and low-Q completeness checks are all defined
there. This file covers parameter physical meanings, residual pattern
interpretation, and common mistakes.

## Model structure

The Unified Fit (Beaucage, 1995/1996) sums levels from smallest to largest
scale. Level 1 is the smallest structure (highest-Q, smallest Rg). Each
level contributes a Guinier term (G, Rg) and a power-law term (B, P).

The highest-numbered level often represents structures too large for their
Guinier region to fall within the measured Q range. Set G = 0, Rg = 10¹⁰,
fix both permanently, and fit only P and B for that level.

## Parameter physical meanings

**Rg** — radius of gyration in Å. The Guinier knee appears at Q ≈ π/Rg.
Estimate from the data before fitting: identify the Q position of each
knee in the log-log plot and compute Rg ≈ π / Q_knee.
- Knee at Q = 0.04 Å⁻¹ → Rg ≈ 78 Å
- Knee at Q = 0.003 Å⁻¹ → Rg ≈ 1050 Å
- Knee at Q = 0.001 Å⁻¹ → Rg ≈ 3140 Å

**G** — Guinier prefactor (cm⁻¹). Sets the intensity of this level at Q→0.
Must satisfy: `5 × I_min ≤ G ≤ I_max` (measured intensity range).

**Critical G-estimation rule:** The best starting estimate is the measured
intensity at Q = 2π/Rg, which is close to the Guinier knee peak. Do NOT
guess or use default 1 — wrong G values cause fits to diverge catastrophically.
From the log-log data plot, find the intensity value at this Q position and
use it directly as G_start.

Exception: the large-scale power-law level has G = 0 by definition.

**P** — power-law exponent (log-log slope). Start fixed at 4; free only if
residuals show systematic slope mismatch in the power-law region.
- P = 4: smooth surface (Porod)
- 3 < P < 4: rough surface or broad size distribution
- P = 3: mass fractal surface or collapsed polymer
- P < 3: mass fractal interior, polymer chains, or size distribution

**B** — power-law prefactor. For smooth surfaces (P ≈ 4):
B ≈ (1.62/Rg)⁴ × G. Enabling estimate_B automates this. B and P are
correlated — if B hits its lower bound, P drifts to compensate.

**RgCO** (RgCutoff) — high-Q exponential roll-off. Default: 0 and fixed
for all levels. Do not change unless the data shows a hierarchical structure
(fractal aggregate, elongated or disk-like particle). When needed:
- RgCO_1 = 0 always (no smaller level exists)
- RgCO_2 = current Rg_1, fixed
- RgCO_3 = current Rg_2, fixed
Never fit RgCO as a free parameter. The preferred way to manage RgCO for
hierarchical structures is `set_level_option(session_id, N, "link_RGCO",
True)`, which keeps RgCO_N automatically synchronized to Rg_(N-1) during
fitting — no manual updates needed after each fit.

**ETA** — correlation distance (Å). Nearest-neighbour centre-to-centre
distance between particles. Physical constraint: ETA ≥ 2 × Rg (particles
cannot overlap). Before fitting ETA: set value = 3 × Rg AND set lower bound
= 2 × Rg. Default ETA = 10 Å is wrong for any level with Rg > 50 Å.

**PACK** — packing factor (0–8). Strength of liquid-like ordering. Default
0 disables the correction entirely. Set to 1 before fitting PACK.

**ETA and PACK are needed when ANY of these signs appear:**
1. Measured intensity drops at Q < π/Rg instead of flattening into a
   plateau (low-Q side of the knee curves downward).
2. The feature looks peaked/sharp rather than a broad rounded knee.
3. Residuals show a +-+ pattern in the level's Q window (π/(2×Rg) to
   2π/Rg): negative low-Q side, positive at the peak, negative high-Q side.

**Critical:** ETA and PACK have NO effect unless the level's `correlations`
boolean flag is True. Always call `set_level_option(session_id, N,
"correlations", True)` before setting ETA/PACK values. The full procedure
is in workflow step 8.

**background** — flat incoherent background. Fit first, fix once converged.

## Level options (boolean flags)

These are separate from numeric parameters. Toggle with
`set_level_option(session_id, level, option, enabled)` and query with
`get_level_options(session_id, level)`. Four options exist:

**correlations** — Enables the Born-Green liquid-like ordering correction for
a level. **Without this flag set to True, ETA and PACK values are silently
ignored in the intensity calculation.** Default is False (off). Must be
explicitly enabled with `set_level_option` before the ETA/PACK fitting
workflow has any effect.

**link_B** — Computes B from G, Rg, and P via the Porod invariant instead of
treating B as a free parameter. With link_B=True, B cannot be fitted. Use the
following strategy:
1. Before the first staged fit on any level, call
   `set_level_option(session_id, N, "link_B", True)`. The fit is more stable
   and converges faster with B automatically computed.
2. Once Rg, G, and P have converged to reasonable values, call
   `set_level_option(session_id, N, "link_B", False)` and free B for a final
   refinement fit.
3. If B diverges significantly after freeing, or the fit becomes unstable,
   reset `link_B=True`. A calculated B is physically reasonable for a Porod
   surface; extreme B values usually indicate B and P are coupled into a local
   minimum.

**link_RGCO** — Automatically keeps level N's RgCO equal to the current Rg of
level N−1. Whenever Rg_(N-1) changes (during fitting or manual assignment),
RgCO_N follows without needing a separate `set_parameter_value` call. Enable
only for structures with true hierarchical coupling: fractal aggregates (level
1 = primary particle, level 2 = aggregate) or elongated/disk-like particles
with two distinct principal dimensions. Do not enable link_RGCO for
independent structural levels.

**mass_fractal** — Not used in this workflow; ignore.

## Residual pattern recognition

**What counts as random (acceptable):** > 5 zero-crossings within the Q
window of a Guinier feature (π/(2×Rg) to 2π/Rg), with no recognizable
shape. High-frequency scatter around zero is noise, not misfit.

**What counts as systematic (must fix before saving):** ≤ 3 zero-crossings
in the feature's Q window with a recognizable shape:

- **+-+ pattern** (negative low-Q side, positive at peak, negative high-Q
  side, or reversed): correlations missing — follow workflow step 8 to
  enable ETA and PACK. Residuals of ±10–25 with this shape are not noise.
- **Monotone slope** across the feature: P is wrong; free P.
- **Single broad hump**: Rg is wrong or a level is missing.
- **S-shaped (negative then positive with increasing Q)**: Rg too large.
- **Inverted S-shape**: Rg too small.
- **Systematic rise at very low Q**: missing large-scale power-law level;
  add highest-numbered level with G = 0, Rg = 10¹⁰, fit only P and B.
- **High residuals only at high Q**: background too low; increase it or
  restrict Q range.
- **High-frequency noise everywhere**: data uncertainties are under-estimated
  (common in SAXS/USAXS data reduction) — this is acceptable if no
  low-frequency systematic pattern is present.

**χ² guidance:** The absolute value of χ²ᵣ is unreliable because data
uncertainties are routinely under- or over-estimated. χ²ᵣ = 37 can be a
good fit; χ²ᵣ = 0.5 can indicate over-fitting. Use χ²ᵣ only to compare
consecutive fits on the same dataset. Judge quality by residual shape only.

## Common mistakes

- **Fitting with default values:** Rg=10 Å, G=1, ETA=10 Å, PACK=0 are all
  wrong defaults. Set Rg from π/Q_knee; set G from I(2π/Rg); set ETA = 3×Rg
  with lower bound 2×Rg; set PACK = 1 — before any fit involving those
  parameters. **Wrong G estimates cause catastrophic divergence** — estimate
  directly from data, do not guess.
- **Catastrophic fit divergence:** If chi² explodes or parameters diverge
  wildly after the first fit, the initial G estimate was wrong. Re-estimate
  each G_N from the data intensity at Q=2π/Rg_N, reset all parameters, and
  refit.
- **Not detecting correlation pattern:** After each fit, count zero-crossings
  in each level's Q window. A +-+ pattern with ≤ 3 crossings means
  correlations are needed, even if the overall fit looks reasonable.
- **ETA below 2×Rg after fitting:** Physically impossible (particle
  overlap). Reset ETA = 3×Rg, enforce lower bound = 2×Rg, refit.
- **Fitting G or Rg of the large-scale power-law level:** Both must remain
  fixed at 0 and 10¹⁰ respectively. Freeing either causes a tool error.
- **RgCO set non-zero without justification:** Default is 0 and fixed.
  Only set RgCO_N = Rg_(N-1) (fixed) when hierarchical structure is needed.
- **Saving before running the correlation check and low-Q check:** Both
  are mandatory workflow steps. Do not call save_fit until both pass.
- **Not calling get_fit_image after every run_fit:** This updates the GUI
  plot so the user can follow progress. Never skip it.
