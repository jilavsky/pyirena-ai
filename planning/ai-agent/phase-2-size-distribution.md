# Phase 2 — Size Distribution as a selectable fit model

Status: **In progress — for testing**

This document is the getting-started + testing guide for the second fitting
model in pyirena-ai: **Size Distribution** (particle P(r) inversion), added
alongside the existing **Unified Fit**. It is a living scaffold — the strategy
and skill prompts are deliberately lean and meant to be tuned against real data.

## What shipped

pyirena's control surface already exposes a complete Size Distribution model
(`pyirena.api.control.sizes`; MCP prefix `pyirena_ctrl_sizes_*`). pyirena-ai's
tool bridge (`pyirena_ai/core/tools.py`) auto-exposes **every**
`pyirena.api.control.__all__` function, so the agent could always *call* the
sizes tools. Phase 2 adds the missing UX + guidance to use them deliberately:

- **Fit-model registry** — `pyirena_ai/core/models.py`. One `FitModel` entry per
  model, mapping a model key to its skill file, default strategy, save tool, and
  live-state tool. Removes the previously-hardcoded `tool_name="unified_fit"`
  from the CLI, both GUI runners, and the chat reload path.
- **Strategy** — `pyirena_ai/config/strategies/size_distribution_default.md`.
  The staged workflow: suggest → configure → background → invert → inspect →
  save.
- **Skill** — `pyirena_ai/config/skills/size_distribution.md`. Parameter
  meanings and result interpretation (method choice, contrast ↔ volume fraction,
  grid heuristic, error handling, complex background, reading P(r)).
- **GUI selector** — a "Fit model" dropdown on both the Fit and Chat tabs.
  Selecting a model flips the strategy dropdown to that model's default strategy
  (still overridable) and steers which skill loads + which save tool the
  one-shot prompt names.
- **CLI** — `pyirena-ai fit … --model {unified,sizes}`.

No pyirena (upstream) changes — its sizes surface is complete and correct.
No reinstall — pyirena is installed editable in the `pyirena-ai` conda env and
the new `.md` files are picked up live.

## The size-distribution workflow (what the agent should do)

1. `open_dataset` → `session_id`.
2. `suggest_sizes_setup` → `suitable`, `recommended` windows, `warnings`.
   If not suitable (e.g. multi-population), recommend Unified Fit and stop.
3. `select_sizes_model(method="maxent")`.
4. `set_shape("sphere", contrast=1.0)` — contrast 1.0 ⇒ *relative* volume fraction.
5. `set_size_grid(r_min, r_max, n_bins=200, log_spacing=True)` from the recommendation.
6. `set_error_handling(error_scale=1.0)`.
7. Complex background: `fit_power_law_background` (low-Q) + `fit_flat_background`
   (high-Q) + `get_background_preview_image` to confirm.
8. `set_fit_q_range(inversion_q_min, inversion_q_max)` — the shared Q-range tool,
   here the inversion window.
9. `run_sizes_fit(random_seed=42)`.
10. `get_sizes_fit_image` — model tracks data? P(r) a clean peak, not at a grid edge?
11. Widen the grid and refit if `peak_r` is at `r_min`/`r_max`.
12. `save_sizes_fit` → report.

## How to test

Run everything in the `pyirena-ai` conda env (it has pyirena + scipy/h5py).

### 0. Smoke-test the wiring (no LLM, no data)

```bash
conda run -n pyirena-ai python -c "from pyirena_ai.core.models import FIT_MODELS, model_choices; print(model_choices())"
conda run -n pyirena-ai pyirena-ai strategies   # should list size_distribution_default
```

### 1. CLI — a dilute single-population dataset (e.g. spheres)

```bash
conda run -n pyirena-ai pyirena-ai fit /path/to/spheres.h5 --model sizes --provider anthropic -v
```

Expect the agent to call `suggest_sizes_setup` → configure → background →
`run_sizes_fit` → `get_sizes_fit_image` → `save_sizes_fit`. Check the audit JSON
in `<data_folder>/pyirena-ai/` records `saved_to` and `final_chi_squared`.

### 2. CLI — Unified Fit regression (must be unchanged)

```bash
conda run -n pyirena-ai pyirena-ai fit /path/to/hierarchical.h5 --model unified -v
```

### 3. GUI

```bash
conda run -n pyirena-ai pyirena-ai gui
```

- Fit tab → set **Fit model = Size Distribution** → the strategy dropdown should
  flip to `size_distribution_default`. Paste a path → ▶ Fit. Watch the two-panel
  sizes image (I(Q) + P(r)) render and the params panel show the sizes config.
- Repeat on the Chat tab; ask follow-ups ("widen the grid and refit").

## What a good result looks like

- Top panel: model + background tracks the data through the inversion window.
- Bottom panel: P(r) is a smooth, plausible peak, well inside the grid (not piled
  at `r_min`/`r_max`), not a forest of noise spikes.
- `peak_r`, `rg`, `volume_fraction` reported; volume fraction flagged *relative*
  when contrast = 1.0.

## Known rough edges to tune

- **Lean prompts.** The strategy/skill are starting scaffolds; expect to tune
  windowing, method selection, and the suitability/guardrail wording against
  real data. Edit the `.md` files and use **🔄 Reload strategy/skills** in the
  Chat tab to apply without restarting.
- **σ mis-scaling.** As with Unified Fit, don't chase a particular χ²; judge from
  the image and P(r) plausibility.
- **Param panel for sizes** shows the model *configuration* (grid/shape/method/
  background), not a free/fixed parameter table — the inversion has no free
  scalar parameters in the Unified-Fit sense.
