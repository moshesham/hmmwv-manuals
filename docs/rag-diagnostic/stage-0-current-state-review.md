# Stage 0 - Current-State Review

## Purpose
Establish a reliable baseline for the interactive diagnostic assistant before retrieval, indexing, or application code is introduced.

## Repository Baseline
- Repository type: static Jekyll/GFM manual corpus.
- Runtime application code: none.
- Existing configuration: `_config.yml` enables `jekyll-relative-links` for static publishing.
- Primary source formats:
  - Markdown manuals and chapter splits.
  - Manual metadata JSON files with OCR and page statistics.
  - Image assets referenced from markdown.
  - Source PDFs in `source-pdf/` for some manuals.

## Corpus Structure Observed
### Manuals currently present
- `tm-9-2320-280-10`
- `TM-9-2320-280-20-1`
- `TM-9-2320-280-20-2`
- `TM-9-2320-280-20-3`
- `TM-9-2320-280-24P`
- `TM-9-2320-387-24-1`
- `TM-9-2320-387-24-2`
- `TM-9-2815-237-34`

### MVP-relevant manuals from the implementation plan
- `tm-9-2320-280-10`
- `TM-9-2320-280-20-1`
- `TM-9-2320-280-20-2`
- `TM-9-2320-280-20-3`

## Source Patterns Confirmed
### Structural strengths
- Task and paragraph anchors exist across manuals, for example `## 1-1. Scope` and `### 3-2. Engine Oil Dipstick Tube Replacement`.
- Troubleshooting content already exists in operator and maintenance manuals.
- Safety language is already embedded as warnings, cautions, and notes.
- Procedures often preserve operational ordering with numbered steps.
- Images are linked inline and can be associated with nearby procedures.
- Metadata files provide page counts and OCR context that can support provenance and quality scoring.

### Structural risks
- Heading and anchor casing is inconsistent, for example `<a name="...">` and `<a NAME="...">`.
- Troubleshooting content appears in multiple shapes: narrative, flow guidance, and tables.
- `INITIAL SETUP` and `FOLLOW-ON TASKS` are present but not perfectly normalized.
- Some content is heavily table-based and may need special handling during parsing.
- OCR artifacts and formatting noise are present in the corpus and should be treated as expected input conditions, not exceptions.

## Representative Evidence
- Static-site configuration: `_config.yml`
- Manual usage and troubleshooting guidance: `TM-9-2320-280-20-1/howto.md`
- Maintenance task with `INITIAL SETUP` and `FOLLOW-ON TASKS`: `TM-9-2320-280-20-2/chapter3.md`
- Diagnostic guide structure: `TM-9-2320-280-20-1/chapter2.md`
- Operator troubleshooting sequence: `tm-9-2320-280-10/tm-9-2320-280-10.md`
- OCR/page metadata: `/home/runner/work/hmmwv-manuals/hmmwv-manuals/TM-9-2320-280-20-1/TM-9-2320-280-20-1_meta.json`

## Current-State Conclusions
1. The repository is a strong source corpus but not yet an application runtime.
2. The content already contains the minimum diagnostic primitives needed for retrieval-grounded assistance.
3. The main near-term challenge is normalization, not content scarcity.
4. Stage 0 should avoid premature model or infrastructure choices and instead lock down source truth, scope boundaries, and evidence requirements.

## Assumptions Challenged
- Assumption: the markdown is already parser-ready.
  - Challenge: the content is parser-usable, but not parser-uniform.
- Assumption: one content model can be designed around procedures only.
  - Challenge: troubleshooting tables and operator guidance need first-class representation.
- Assumption: citations can be deferred until orchestration.
  - Challenge: provenance has to exist in the canonical model before retrieval is built.

## Open Questions
1. Should source PDFs be treated only as audit references, or as fallback inputs for disputed markdown sections?
2. Are image references required in the MVP answer path, or only as supporting metadata for later UX stages?
3. Should operator-level troubleshooting and unit-maintenance diagnostics be ranked together or separated by mode?

## Exit Criteria for Stage 0
- Current repository constraints are documented.
- MVP candidate manuals are confirmed.
- Known content-shape risks are recorded.
- Provenance and safety have been established as non-optional design constraints.
