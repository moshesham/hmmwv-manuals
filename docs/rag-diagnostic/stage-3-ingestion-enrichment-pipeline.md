# Stage 3 — Ingestion and Enrichment Pipeline

## Objective
Build a deterministic, schema-validated ingestion pipeline that converts the raw HMMWV manual markdown corpus into structured content units, produces enrichment artifacts, and validates corpus health — so that Stage 4 receives a clean, fully-provenance-tracked dataset ready for embedding and indexing.

---

## Assessment: What the corpus gives us

### Positive signals
- Chapters are already split into individual markdown files per manual, giving natural segment boundaries.
- Anchors (`<a name="X-Y">`) are present and correspond to task and section headings.
- Troubleshooting tables use consistent `### X-Y. Task Title` heading patterns.
- Safety blocks use recognizable keywords: `### Warning`, `### .Warning.`, `### Caution`, `NOTE`.
- `INITIAL SETUP` and `FOLLOW-ON TASKS` appear as prose headings directly inside task sections.
- Cross-references follow a stable pattern: `TM 9-2320-280-XX-Y`, paragraph numbers, and task anchors.

### Known complications
- OCR artifacts: spacing noise in headings (e.g., `G E N E R A L`, `I N T E Rva L S`), inconsistent casing.
- Safety marker styles vary: `### Warning`, `### .Warning.`, all-caps `WARNING`, inline bold `**WARNING**`.
- Multi-page troubleshooting flows span dozens of sequential headings without an explicit container boundary.
- Some tasks have no `INITIAL SETUP` or no `FOLLOW-ON TASKS` — parser must not fail on absence.
- A small number of task headings are duplicated (table of contents rows vs. actual content).

### Revised parsing strategy after assessment
1. Parse the table-of-contents block at the top of each chapter first, then skip re-parsing it as content.
2. Detect anchor-headed tasks as the atomic unit boundary, not page boundaries.
3. Treat any heading-keyword match (Warning/Caution/Note) as a safety block regardless of OCR noise.
4. Promote sequences of troubleshooting headings (pattern `### X-YY.` with question/test language) into `troubleshooting_entry` units with graph edges inferred from yes/no branches.
5. Gracefully skip or quarantine any content unit that cannot be unambiguously classified.

---

## Pipeline Design

```
Corpus (markdown + meta JSON)
       │
       ▼
┌─────────────────────┐
│  1. Source Loader   │  — Discovers all chapter files for the 4 MVP manuals.
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  2. Markdown Parser │  — Segments at anchor/heading boundaries,
│                     │    extracts raw block types.
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  3. Domain Chunker  │  — Assembles coherent content units:
│                     │    keeps procedure steps + safety + setup together,
│                     │    builds troubleshooting graph containers.
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  4. Enrichment      │  — Adds keyword index, cross-reference map,
│                     │    structured troubleshooting graph edges.
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  5. Schema Validate │  — Validates every unit against
│                     │    content-unit.schema.json v1.1.0.
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  6. QA Checks       │  — Coverage, broken anchors,
│                     │    missing safety associations.
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  7. Output Writers  │  — JSONL content-unit file,
│                     │    keyword index JSON,
│                     │    cross-reference map JSON,
│                     │    troubleshooting graph JSON,
│                     │    QA report Markdown.
└─────────────────────┘
```

---

## Module Breakdown

### `ingestion/loader.py`
- `discover_sources(corpus_root, manual_ids)` — walks the MVP manual directories, yields `(manual_id, manual_role, chapter_file, meta_file)` tuples.
- Reads `*_meta.json` for manual-level metadata (ID, role, publication date).
- Returns a stable, sorted list of sources so ingestion is deterministic across runs.

### `ingestion/parser.py`
- `parse_chapter(path, manual_id, manual_role)` — returns a list of `RawBlock` objects.
- `RawBlock` fields: `anchor`, `heading`, `heading_level`, `body_lines`, `line_start`, `line_end`, `source_path`.
- **TOC detection**: recognizes the leading markdown table with `Task | Description` as TOC; marks those blocks as `toc` type and excludes from content units.
- **Safety detection**: matches `WARNING`, `.WARNING.`, `CAUTION`, `.CAUTION.`, `NOTE`, `### Warning`, `### Caution` (case-insensitive, strip OCR dots/spaces).
- **INITIAL SETUP / FOLLOW-ON TASKS detection**: inline string match within task body.
- **Step detection**: numbered list items `(1)`, `(2)`, `a.`, `b.`, `1.`, `2.` immediately following task body.

### `ingestion/chunker.py`
- `build_content_units(raw_blocks, manual_id, manual_role, source_path)` — assembles `ContentUnit` objects.
- **Procedure task** assembly:
  - Unit starts at a task anchor heading `### X-Y. Title`.
  - Unit ends at the next peer-level anchor heading.
  - INITIAL SETUP, ordered steps, safety blocks, and FOLLOW-ON TASKS all fold into the same unit.
  - If the task body exceeds 8 000 chars, it may be split into `procedure_step_group` sub-units with shared parent provenance.
- **Troubleshooting entry** assembly:
  - Detects the troubleshooting section boundary by heading text keywords (e.g., `Troubleshooting`, `Tests`, `Startability`, `Compression`).
  - Within that section, each `### X-Y.` sub-heading becomes one `troubleshooting_entry`.
  - Infers yes/no edges from indented YES/NO markers and `go to step` language.
- **Diagnostic flow** promotion:
  - When a sequence of `troubleshooting_entry` units shares a common section heading, promotes them into a `diagnostic_flow` container with linked `diagnostic_flow_node` children.
- **Safety summary** extraction:
  - Free-standing warning/caution sections not attached to a task become `safety_summary` units.

### `ingestion/enrichment.py`
- `build_keyword_index(units)` — for each unit, extracts symptom terms, component names, and tool names using a term list from `schemas/rag-diagnostic/taxonomy.json`. Returns a dict `{term → [content_id, ...]}`.
- `build_cross_reference_map(units)` — parses `relations.cross_manual_refs` from all units, builds a bidirectional map `{source_content_id → [target_manual, target_anchor, target_section]}`.
- `build_troubleshooting_graph(units)` — takes `diagnostic_flow` and `diagnostic_flow_node` units, produces a NetworkX-compatible adjacency dict with node labels, edge semantics (yes/no/continue/fail), and support panel associations.

### `ingestion/qa.py`
- `check_coverage(units, expected_manuals)` — reports which manuals and chapters produced zero content units.
- `check_broken_anchors(units, source_paths)` — for each `cross_manual_refs` target, verifies that a unit with a matching anchor exists in the output.
- `check_safety_associations(units)` — flags any `procedure_task` or `diagnostic_flow_node` that contains step text with risk keywords but has no attached `warnings` or `cautions`.
- `check_duplicate_ids(units)` — detects colliding `content_id` values.
- `write_qa_report(issues, out_path)` — writes a Markdown QA report with counts per check and per-manual summaries.

### `ingestion/models.py`
- `ContentUnit` dataclass mirroring `content-unit.schema.json` v1.1.0 fields.
- `to_dict()` / `from_dict()` helpers.
- `generate_content_id(manual_id, anchor, chunk_index)` — deterministic ID generator.

### `ingestion/validate.py`
- `validate_unit(unit_dict, schema_path)` — uses `jsonschema` to validate against the canonical schema. Returns `(is_valid, errors)`.
- Produces per-unit validation results that feed the QA report.

### `ingestion/run_ingestion.py`
- CLI entrypoint: `python -m ingestion.run_ingestion --corpus-root . --output-dir output/ingestion`.
- Progress reporting to stdout with counts and timing.
- Exits non-zero if QA check failure rate exceeds configured threshold.

---

## Output Artifacts

| File | Format | Description |
|------|--------|-------------|
| `output/ingestion/content-units.jsonl` | JSONL | One validated content unit per line |
| `output/ingestion/keyword-index.json` | JSON | Term → content ID list |
| `output/ingestion/cross-reference-map.json` | JSON | Bidirectional cross-manual reference map |
| `output/ingestion/troubleshooting-graph.json` | JSON | Adjacency dict for diagnostic flows |
| `output/ingestion/qa-report.md` | Markdown | Coverage, anchor, safety, duplicate checks |

---

## QA Checks — Pass Criteria

| Check | Failure condition |
|-------|-----------------|
| Coverage | Any MVP chapter produces zero units |
| Broken anchors | Any cross-ref target has no matching unit |
| Safety associations | More than 5% of procedure tasks with risk language have no safety block |
| Duplicate IDs | Any duplicate `content_id` |
| Schema validation | Any unit fails schema validation |

---

## Local Performance Targets
- Full ingestion run (all 4 manuals): **under 60 seconds** on a laptop without GPU.
- No network I/O at ingestion time.
- Output directory is fully reproducible: two runs on the same corpus produce byte-identical JSONL.

---

## Assumptions Challenged

- **Assumption**: OCR quality is uniform across manuals.
  - **Finding**: Heading noise (spaced letters, stray dots) is localized to section-label headings, not to task headings. Task headings are reliably parsable.
- **Assumption**: All tasks follow the INITIAL SETUP → Steps → FOLLOW-ON TASKS structure.
  - **Finding**: Many reference-section tasks have no INITIAL SETUP. Parser must handle gracefully.
- **Assumption**: Troubleshooting graphs can be inferred from heading structure alone.
  - **Finding**: YES/NO markers exist inline but are not always present; graph edges default to `continue` when absent, preserving sequence without asserting branching.

---

## Residual Questions
1. Should `procedure_step_group` sub-units also be independently retrievable, or only the parent `procedure_task`?
2. What is the right threshold for the safety-association QA check (currently 5%)?
3. Should quarantined taxonomy candidates be emitted into the JSONL or a separate quarantine file?
