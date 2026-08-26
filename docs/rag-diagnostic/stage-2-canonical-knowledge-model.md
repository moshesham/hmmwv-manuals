# Stage 2 - Canonical Knowledge Model

## Objective
Define the normalized unit of knowledge that later ingestion, retrieval, and orchestration stages will use without losing safety, order, or provenance.

## Canonical Content Unit
The canonical content unit is the smallest independently retrievable manual segment that still preserves its operational meaning.

### Design rules
1. A task remains whole when splitting it would separate `INITIAL SETUP`, ordered steps, safety blocks, or `FOLLOW-ON TASKS`.
2. Troubleshooting decision content remains whole when splitting it would destroy decision flow semantics.
3. Provenance is mandatory and captured per content unit.
4. Taxonomy is additive metadata, not a replacement for source text.

## Normalized Fields
The authoritative field definition lives in `/home/runner/work/hmmwv-manuals/hmmwv-manuals/schemas/rag-diagnostic/content-unit.schema.json`.

Key field groups:
- Identity: content ID, manual ID, source path, anchor, heading.
- Source location: line start, line end, chunk ID, excerpt.
- Classification: unit type, manual role, chapter, section, subsystem, maintenance category.
- Safety: warning, caution, and note blocks tied to the unit.
- Procedure structure: initial setup, ordered steps, follow-on tasks.
- Troubleshooting structure: symptom, condition, question, yes/no or ordered branches.
- Relations: cross-manual references, image references, follow-on links.
- Provenance: exact excerpt, metadata source, and parser confidence.

## Unit Types
- `procedure_task`
- `procedure_step_group`
- `troubleshooting_entry`
- `diagnostic_flow`
- `reference_section`
- `safety_summary`

## Parsing Strategy
### 1. Manual segmentation
- Segment at chapter and task heading boundaries first.
- Preserve nearby anchors exactly as source identifiers.
- Keep chapter-split markdown files as the primary ingestion source.

### 2. Task extraction
- Detect task headings such as `### 3-2. Engine Oil Dipstick Tube Replacement`.
- Attach all content until the next peer task heading.
- Capture `INITIAL SETUP`, ordered steps, images, and `FOLLOW-ON TASKS` inside the same unit unless a later stage proves a safe sub-split.

### 3. Troubleshooting extraction
- Detect operator troubleshooting tables and maintenance diagnostic guide structures as dedicated unit types.
- Preserve explicit order, question numbering, and branching semantics.
- Record when a troubleshooting item escalates to another manual or maintenance level.

### 4. Safety extraction
- Recognize warnings, cautions, and notes regardless of case or heading style.
- Attach safety blocks to the nearest valid task or troubleshooting decision that they govern.
- Preserve original wording for citation and user display.

### 5. Cross-reference extraction
- Record manual references, paragraph references, and task references as structured relations.
- Preserve source strings exactly; normalize derived targets separately.

## Provenance Model
Each unit must retain:
- Source file path.
- Source anchor or heading.
- Source line range.
- Exact excerpt used for the unit.
- Metadata origin when OCR or page statistics are relevant.
- Parser confidence flag for later QA.

## Taxonomy Model
The baseline taxonomy lives in `/home/runner/work/hmmwv-manuals/hmmwv-manuals/schemas/rag-diagnostic/taxonomy.json`.

Initial facets:
- Manual role.
- Vehicle subsystem.
- Symptom.
- Component.
- Maintenance category.
- Safety severity.
- Tool and material requirements.

## Normalization Standards
- Preserve source markdown and produce normalized plain text alongside it.
- Store source identifiers exactly as written and add normalized equivalents only as separate metadata.
- Do not flatten ordered procedures into unordered text.
- Do not strip warnings, cautions, or notes during chunking.

## Assumptions Challenged
- Assumption: embedding-oriented chunk size should define the schema.
  - Challenge: operational meaning and safety boundaries define the schema first.
- Assumption: plain text is enough.
  - Challenge: markdown, images, and structured blocks carry procedural context.
- Assumption: one parser rule will work across all manuals.
  - Challenge: operator troubleshooting, maintenance tasks, and diagnostic flows need different extraction patterns under one common model.

## Open Questions
1. Should multi-page decision trees remain single units with internal nodes, or be represented as linked unit chains?
2. Should taxonomy values be strictly controlled from day one, or allow staged enrichment with confidence scoring?
3. How should later stages represent conflicting instructions when one task cites another manual revision or role boundary?
