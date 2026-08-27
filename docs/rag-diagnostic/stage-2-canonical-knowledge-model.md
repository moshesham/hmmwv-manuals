# Stage 2 - Canonical Knowledge Model

## Objective
Define the normalized unit of knowledge that later ingestion, retrieval, and orchestration stages will use without losing safety, order, provenance, or mode-routing context.

## Canonical Content Unit
The canonical content unit is the smallest independently retrievable manual segment that still preserves its operational meaning.

### Design rules
1. A task remains whole when splitting it would separate `INITIAL SETUP`, ordered steps, safety blocks, or `FOLLOW-ON TASKS`.
2. Troubleshooting decision content remains whole when splitting it would destroy decision flow semantics.
3. Multi-page diagnostics are stored as graph-backed logical flows, not page-sized prose chunks.
4. Provenance is mandatory and captured per content unit and, where needed, per flow node or support panel.
5. Taxonomy is split between controlled routing metadata and flexible candidate vocabulary.

## Normalized Fields
The authoritative field definition lives in `schemas/rag-diagnostic/content-unit.schema.json`.

Key field groups:
- Identity: content ID, manual ID, source path, anchor, heading.
- Source location: line start, line end, chunk ID, excerpt.
- Mode metadata: detected mode, selected mode, source of selection, confidence, persistence threshold, override allowed, automatic persistence allowed, clarification required.
- Classification: unit type, manual role, chapter, section, subsystem, maintenance category.
- Safety: warning, caution, and note blocks tied to the unit.
- Procedure structure: initial setup, ordered steps, follow-on tasks.
- Troubleshooting structure: symptom, question, yes/no or ordered branches.
- Diagnostic graph structure: flow container, nodes, edges, support panels, dual rendering metadata.
- Relations: cross-manual references, image references, follow-on links.
- Provenance: exact excerpt, metadata source, and parser confidence.
- Taxonomy: controlled core, candidate terms, and quarantine bucket.

## Unit Types
- `procedure_task`
- `procedure_step_group`
- `troubleshooting_entry`
- `diagnostic_flow`
- `diagnostic_flow_node`
- `diagnostic_support_panel`
- `reference_section`
- `safety_summary`

## Hybrid Mode Metadata
Every retrievable unit should carry routing metadata that supports:
- inferred-first mode selection
- explicit override
- `mixed_or_uncertain` handling
- confidence-based session persistence

Mode metadata is routing state, not a replacement for source provenance.

## Graph-Based Diagnostic Flow Model
### Flow container
A multi-page diagnostic flow is represented by a single flow container that holds:
- flow identity for retrieval
- entry node identifiers
- source span metadata
- dual rendering preferences

### Decision nodes
Each node represents a meaningful logic boundary such as:
- question
- action
- check
- outcome
- escalation

### Edges
Edges preserve explicit traversal semantics such as:
- yes
- no
- pass
- fail
- continue
- branch-to-reference

### Support panels
Support panels capture nearby right-page material such as:
- test instructions
- notes
- warnings
- cautions
- measurement help
- reference aids

### Dual rendering
- Retrieval view: node-level precision for search and reranking.
- Technician view: reconstructed guided path that reads linearly while preserving branch logic.

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
- Promote multi-page decision material into graph-backed flow containers with linked nodes and support panels.
- Record when a troubleshooting item escalates to another manual or maintenance level.

### 4. Safety extraction
- Recognize warnings, cautions, and notes regardless of case or heading style.
- Attach safety blocks to the nearest valid task, flow node, or support panel that they govern.
- Preserve original wording for citation and user display.

### 5. Cross-reference extraction
- Record manual references, paragraph references, and task references as structured relations.
- Preserve source strings exactly; normalize derived targets separately.

### 6. Taxonomy extraction
- Populate controlled core taxonomy only from approved value sets.
- Preserve candidate vocabulary with original term, normalized term, confidence score, and optional canonical mapping.
- Route ambiguous or low-confidence candidates into quarantine instead of blocking ingestion.

## Provenance Model
Each unit must retain:
- Source file path.
- Source anchor or heading.
- Source line range.
- Exact excerpt used for the unit.
- Metadata origin when OCR or page statistics are relevant.
- Parser confidence flag for later QA.

For graph-backed flows, nodes and support panels may carry their own local provenance in addition to the flow container provenance.

## Semi-Controlled Taxonomy Model
The baseline taxonomy lives in `schemas/rag-diagnostic/taxonomy.json`.

### Controlled core
- Manual role.
- Vehicle subsystem.
- Maintenance category.
- Safety type.

### Candidate vocabulary
- Symptom terms.
- Component terms.
- Aliases.
- OCR-noisy variants.

### Quarantine
- Low-confidence or ambiguous candidate terms.
- Terms withheld from retrieval filters until reviewed or mapped.

## Normalization Standards
- Preserve source markdown and produce normalized plain text alongside it.
- Store source identifiers exactly as written and add normalized equivalents only as separate metadata.
- Do not flatten ordered procedures into unordered text.
- Do not strip warnings, cautions, or notes during chunking.
- Do not model multi-page branching logic as a single prose blob when graph structure is present in the source.

## Assumptions Challenged
- Assumption: embedding-oriented chunk size should define the schema.
  - Challenge: operational meaning and safety boundaries define the schema first.
- Assumption: page boundaries are the right storage boundaries for diagnostics.
  - Challenge: logic boundaries matter more than page boundaries.
- Assumption: early strictness automatically improves taxonomy quality.
  - Challenge: over-strict taxonomy blocks ingestion and forces premature ontology decisions.
- Assumption: plain text is enough.
  - Challenge: markdown, images, structured blocks, and support panels carry procedural context.

## Residual Questions
1. Should later orchestration stages expose node-level provenance in every answer or only on demand?
2. What review workflow should promote quarantined candidate terms into controlled mappings?
3. Should guided-path rendering collapse low-importance support panels by default on mobile devices?
