# 06 — Entry-Authoring Tool (`reflib`) — Plan

**Status:** Draft — for review
**Purpose:** You correctly don't want to hand-write `entry.json`. This plans the
tool that turns "I just did a good fit and saved it to a NXcanSAS file" into a
validated library entry, prefilling everything a machine can and prompting you
only for what it cannot.

Companions: entry contract in
[`04-reference-library-and-memory.md`](04-reference-library-and-memory.md);
fingerprint in [`05-descriptor-spec-v1.md`](05-descriptor-spec-v1.md).

---

## 1. The workflow it supports (your described flow)

```
find a good new teaching example
  -> fit it in pyirena, save results into the NXcanSAS file   (you do this already)
  -> `reflib add sample.h5`                                   (the new tool)
       - reads the fit + data + metadata from the file
       - computes descriptors (spec 05)
       - extracts curve.csv + thumb.png
       - writes a PREFILLED entry.json with TODO markers on the human-only fields
       - opens it for you to fill in the reasoning / physics / artifacts
       - validates on save; refuses to write an invalid or still-TODO entry
  -> entries/<id>/ now holds a complete, schema-valid record
```

Two invocation modes, same core:

- **`reflib add <file>` (interactive, Pass B):** one file, prefill + prompt for
  human fields. This is your everyday curation flow.
- **`reflib harvest <folder>` (batch, Pass A):** many files, prefill only,
  write entries with `label_confidence="medium"`, `labeled_by="auto"`, and human
  fields left empty/`null`. For bulk-seeding the corpus from your archive; you
  curate the interesting ones later with `reflib edit <id>`.

---

## 2. Machine-derivable vs. human-only (the field split)

The tool's whole value is knowing which is which. It **never** guesses a
human-only field.

| Block / field | Source | Who fills it |
|---|---|---|
| `entry_id` | hash of curve+source | machine |
| `schema_version`, `descriptors.descriptor_version` | constant | machine |
| `provenance.*` (instrument, geometry, q_units, date, operator, sample) | NXcanSAS metadata (`read_metadata`) | machine, human confirms `geometry` if absent |
| `data.*` + `curve.csv` | `read_reduced_data` | machine |
| `descriptors.*` | `detect_features` + spec 05 | machine |
| `label.tool`, `label.config`, `label.fit_quality`, `label.fit_q_range` | the saved fit (`read_unified_fit` / `read_size_distribution` / `read_simple_fit`) | machine |
| `quality.trusted_q_range` | seed = `label.fit_q_range` | machine seeds, **human confirms** |
| `quality.artifacts[]` | — | **human** (why you rejected regions) |
| `descriptors.oscillations` confirm real vs artifact | flagged by machine | **human confirms** |
| `rationale.*` (decision cues, why-this-not-that) | — | **human** |
| `domain_context.*` (chemistry, prep, TEM/APT, refs) | partially from metadata if present | **human** |
| `meta.label_confidence`, `split`, `tags` | — | **human** (defaults offered) |

**Answering your comment question directly:** physics/chemistry facts →
`domain_context` (structured: composition, prep, complementary data, refs);
the *argument* for why you did what you did → `rationale` (`decision_cues`,
`expert_notes`, `alternatives_considered`). The tool presents these as labeled
prompts so there's always an obvious place to put a thought, and none of it
leaks into fields you'll later want to filter/cluster on.

---

## 3. Architecture

Five small, independently testable pieces:

1. **Reader** — thin wrapper over existing pyirena read API / MCP tools
   (`read_reduced_data`, `read_unified_fit`, `read_size_distribution`,
   `read_simple_fit`, `read_metadata`). Input: NXcanSAS path. Output: an
   in-memory `RawFit` dict. No new physics — reuses what the MCP server already
   exposes.
2. **Descriptor engine** — implements spec 05 over the reduced curve. Shared with
   the agent's runtime path (same code that fingerprints unknown curves), so the
   library and live queries use identical descriptors. **Single source of truth
   for descriptors.**
3. **Assembler** — merges Reader + Descriptor output into an `entry.json`
   skeleton, inserts `"__TODO__"` sentinels for human-only fields, writes
   `curve.csv` and `thumb.png`, computes `entry_id`.
4. **Filler (interactive)** — how the human completes the record. Tiered by
   effort (pick one to build first, others later):
   - **v0 (lowest effort, recommended first):** write the prefilled JSON with
     TODO sentinels + inline `// comment` guidance to a temp file, open `$EDITOR`,
     re-validate on close. Zero UI code. A scientist editing JSON is fine for
     Pass B volumes.
   - **v1:** a terminal form (one prompt per human field, showing the thumbnail
     path + the machine-derived context so you answer with the curve in view).
   - **v2:** a small panel in the existing `pyirena_ai/gui` — show the fit image,
     click-drag to mark artifact q-ranges, type rationale. Highest value,
     highest cost; do only if daily use justifies it.
5. **Validator + Writer** — `jsonschema` validate against
   `schema/entry.schema.json`; **reject** if any `__TODO__` remains in a required
   field or `label`/`quality` invariants fail; write atomically to
   `entries/<entry_id>/`. Same validator runs in CI over the whole corpus.

Guardrails: refuse to overwrite an existing `entry_id` unless `--force`; refuse
to write if `provenance.geometry` is `unknown` and mode is interactive (make you
resolve it); dedupe by content hash.

---

## 4. Where it lives

New subpackage `pyirena_ai/reflib/` (reader, descriptors, assembler, filler,
validator) + a CLI entry point `reflib` (mirrors the existing console-script
pattern in `pyproject.toml`). The **descriptor engine is imported by both**
`reflib` and the agent runtime — do not fork it.

---

## 5. Milestones

- **M0 — schema + spec frozen.** Depends on your review of docs 04 & 05. Blocks
  everything.
- **M1 — Reader + Assembler + Validator, batch mode.** `reflib harvest` produces
  schema-valid prefilled entries (human fields null). Test against a handful of
  archive files. *Deliverable: you can point it at one folder and get valid
  entries.* (This is also the §8 "definition of done" item in doc 04.)
- **M2 — Descriptor engine to spec 05**, wired into the Assembler and shared with
  the runtime path. Golden-file tests: fixed curves → fixed descriptors.
- **M3 — Filler v0** (`$EDITOR` round-trip) → `reflib add` interactive flow end
  to end. *Deliverable: your described workflow works.*
- **M4 — Filler v1** (terminal form) if v0 proves clunky at volume.
- **M5 — GUI panel (v2)** only if warranted.

M1+M3 together deliver the whole workflow you described; M4/M5 are ergonomics.

---

## 6. Open questions for review

1. Editor round-trip (v0) vs. a form (v1) for first build — how many entries do
   you realistically author per session? (Drives whether v0 is enough.)
2. Should `reflib harvest` auto-run over the entire archive once (thousands of
   medium-confidence entries), or only on folders you point it at? Bulk seeding
   helps retrieval coverage but adds noise; my lean is opt-in per folder.
3. Do your saved NXcanSAS fits already carry enough metadata to fill
   `provenance.geometry` automatically, or will that always need human
   confirmation? (Determines how much M1 can do unattended.)
