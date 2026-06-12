# Unified Fit — Parameter Reference and Residual Guide

Reference for the Beaucage Unified Fit model. The fitting workflow,
ordering invariant, validity rules, and mandatory checks are defined in
the strategy file — this file is *only* for parameter meanings, residual
shape interpretation, and level-option semantics.

## Model structure

The Unified Fit (Beaucage, 1995/1996) sums structural levels from
smallest to largest. Level 1 is the smallest structure (highest-Q knee,
smallest Rg). Each level contributes a Guinier term (G, Rg) and a
power-law term (B, P), plus an optional high-Q roll-off (RgCO) and an
optional correlation correction (ETA, PACK).

The highest-numbered level often represents structures too large for
their Guinier region to fall within the measured Q range — by convention
this level has G = 0 and a very large fixed Rg, leaving only the
power-law contribution.

## Parameter meanings

**Rg** — radius of gyration in Å. The visible Guinier knee on a log-log
plot is around Q·Rg ≈ 1, so `Rg ≈ 1/Q_knee` is a useful rough estimate.
The Guinier approximation is valid for Q·Rg ≲ 1.3. Use
`fit_local_guinier(session_id, q_min, q_max)` on a window centered on
the knee to obtain a numerically reliable Rg — the visual estimate is
only for choosing window boundaries.

**G** — Guinier prefactor (cm⁻¹). Sets the level's intensity at Q→0.
Obtain from `fit_local_guinier` together with Rg — never read off the
plot. By convention the large-scale power-law level has G = 0.

**P** — power-law exponent (log-log slope). Physical interpretation:
- P = 4: smooth surface (Porod)
- 3 < P < 4: rough surface or broad size distribution
- P = 3: mass fractal surface or collapsed polymer
- P < 3: mass fractal interior, polymer chains, or size distribution

Obtain a starting value from `fit_local_power_law` on the linear
power-law portion of the log-log plot (between knees, or above the
highest-Q knee). If no clean power-law region is visible, start at P = 4.

**B** — power-law prefactor. Obtain from `fit_local_power_law` together
with P. B and P are correlated — if B hits its lower bound, P drifts
to compensate. For smooth surfaces (P ≈ 4) B is tied to G and Rg
through the Porod relation; enabling `link_B` (see level options) has
the model compute B automatically instead of fitting it freely.

**RgCO** (RgCutoff) — high-Q exponential roll-off. Defaults to 0 (off)
and should remain so unless the data shows a true hierarchical
structure (fractal aggregate, or elongated/disc-like particle with two
principal dimensions). When needed, RgCO_N is tied to Rg_(N-1) — the
cleanest way to do this is `link_RGCO=True`. Never fit RgCO as a free
parameter.

**ETA** — correlation distance in Å. Approximately the nearest-neighbour
centre-to-centre distance between particles. As a soft physical floor,
ETA should not be much smaller than ~2·Rg (near-spherical particles
would overlap); for very anisotropic shapes a smaller ETA can still be
physical. Default ETA = 10 Å is wrong for any level with Rg ≳ 50 Å.

**PACK** — packing factor (0–8). Strength of liquid-like ordering.
Default 0 disables the correction entirely.

**background** — flat incoherent background. Fit first, then fix.

ETA and PACK have **no effect** unless the level's `correlations` flag
is True (see level options). Without that flag, changes to ETA or PACK
values are silently ignored by the intensity calculation.

## Level options (boolean flags)

Set with `set_level_option(session_id, level, option, enabled)`. Four
options exist:

**correlations** — Enables the Born-Green liquid-like ordering
correction. ETA and PACK are inactive until this is True. Default False.

**link_B** — Computes B from G, Rg, and P via the Porod invariant
instead of treating B as a free parameter. With `link_B=True`, B
cannot be fitted; this removes one degree of freedom and stabilises
early staged fits.

**link_RGCO** — Keeps level N's RgCO synchronised to the current Rg of
level N−1 automatically. Enable only for genuinely coupled levels
(primary particle + fractal aggregate, or two principal dimensions of
a non-spherical particle). Do not enable for independent structural
levels.

**mass_fractal** — Not used in this workflow; ignore.

## Residual pattern recognition

Define each level's "feature window" as roughly `Q_knee/2` to
`2·Q_knee`, i.e. about `1/(2·Rg)` to `2/Rg`. Count zero-crossings of
the normalised residuals inside that window:

- **> 5 zero-crossings, no recognisable shape** — random scatter,
  acceptable.
- **≤ 3 zero-crossings with a recognisable shape** — systematic misfit
  (see patterns below).

Common systematic shapes:

- **+-+ across the knee** (negative low-Q side, positive at the peak,
  negative high-Q side, or reversed): particle–particle correlations
  are missing — enable `correlations` and fit ETA/PACK for that level.
  Residuals of ±10–25 with this shape are misfit, not noise.
- **Monotone slope across the feature**: P is wrong; free P.
- **Single broad hump**: Rg is wrong, or a level is missing.
- **S-shape (negative then positive with increasing Q)**: Rg too large.
- **Inverted S-shape**: Rg too small.
- **Systematic rise at very low Q**: a large-scale power-law level is
  missing — add one at the high end with G = 0 and very large fixed Rg,
  and fit only P and B for it.
- **High residuals only at high Q**: background too low, or the upper
  fit Q range needs restricting.
- **High-frequency noise everywhere**: data uncertainties are
  under-estimated (common in SAXS/USAXS reduction). Acceptable provided
  no low-frequency systematic pattern is present.

## χ² guidance

The absolute value of χ²ᵣ is unreliable because SAXS/USAXS data
uncertainties are routinely mis-estimated. χ²ᵣ = 37 can be a good fit;
χ²ᵣ = 0.5 can indicate over-fitting. Use χ²ᵣ only to compare
consecutive fits on the same dataset. Judge fit quality from residual
shape.
