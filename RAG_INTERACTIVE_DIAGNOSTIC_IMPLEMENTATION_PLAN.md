# Local LLM + RAG Interactive HMMWV Diagnostic Assistant  
## Detailed Implementation Plan

## 0) Current-State Review
- The repository is a content-first corpus of technical manuals (markdown), images, and metadata JSON files.
- The current delivery model is static content (Jekyll/GFM) with no runtime LLM or retrieval backend.
- The manuals already include key diagnostic structures: troubleshooting sections, task anchors, warnings/cautions, initial setup blocks, and follow-on tasks.

## Stage 1 — Scope, Safety, and Acceptance Criteria
1. Define MVP manual coverage (start with TM-9-2320-280-20-1/2/3 and TM-9-2320-280-10).
2. Define core user journeys:
   - Symptom-to-diagnostic guidance.
   - Step-by-step repair procedure guidance.
   - Follow-up Q&A during troubleshooting.
3. Define safety constraints:
   - Surface warnings/cautions before relevant steps.
   - Never provide uncited procedural advice.
   - Always reference manual/chapter/task source.
4. Define measurable success criteria:
   - Retrieval relevance.
   - Citation accuracy.
   - Step sequence correctness.
   - Verified local/offline operation.

## Stage 2 — Canonical Knowledge Model
1. Define normalized data schema for content units:
   - Manual ID, chapter, section, task/anchor, heading type, body text, safety blocks, follow-on tasks, image refs, source path.
2. Define parsing strategy for:
   - Anchor-based task sections.
   - Troubleshooting flows.
   - INITIAL SETUP and FOLLOW-ON TASKS blocks.
   - Warning/Caution/Note extraction.
3. Define provenance model:
   - Exact source file + chunk ID + source excerpt.
4. Define taxonomy tags:
   - Vehicle subsystem, symptom, component, maintenance category, tool/part requirements.

## Stage 3 — Ingestion and Enrichment Pipeline
1. Build deterministic ingestion from repository markdown and metadata JSON.
2. Apply domain-aware chunking:
   - Preserve contiguous procedure steps.
   - Keep safety content attached to associated procedure chunks.
   - Keep troubleshooting decision units intact.
3. Generate enrichment artifacts:
   - Symptom/component keyword index.
   - Cross-reference map across manuals.
   - Structured troubleshooting graph.
4. Add ingestion QA checks:
   - Coverage completeness.
   - Broken anchors/links.
   - Missing safety block associations.

## Stage 4 — Local Embeddings and Vector Index
1. Select an open-source local embedding model compatible with target hardware.
2. Build vector index with metadata filters (manual, section, subsystem, safety flag).
3. Implement hybrid retrieval (semantic + keyword).
4. Add reranking layer for top-k relevance improvement.
5. Define incremental re-index workflow for content updates.

## Stage 5 — Local LLM Runtime in Docker
1. Containerize local inference runtime (open-source model hosting stack).
2. Define model strategy:
   - Primary instruct model.
   - Optional fallback model for constrained hardware.
3. Define deployment profiles:
   - CPU baseline.
   - GPU accelerated.
4. Ensure no external API dependency at inference time.
5. Add health checks and startup readiness validation.

## Stage 6 — RAG Orchestration Service
1. Implement orchestration layer:
   - Query interpretation.
   - Retrieval and reranking.
   - Prompt assembly with grounded context.
2. Support response modes:
   - Diagnostic flow mode.
   - Procedure execution mode.
   - Clarifying-question mode.
3. Enforce grounded outputs:
   - Mandatory citations in each answer.
   - Confidence-aware “insufficient evidence” behavior.
4. Maintain conversational state:
   - Vehicle context, subsystem focus, current step, completed checks.

## Stage 7 — Technician-Facing Interactive Experience
1. Build an interactive workflow:
   - Input symptom.
   - Receive ranked likely diagnostic path.
   - Drill into explicit steps with references.
2. Add step execution controls:
   - Complete / blocked / unclear status.
   - Ask follow-up at any step.
3. Implement safety-first UX:
   - Persist warning/caution visibility.
   - Require acknowledgement for high-risk steps.
4. Provide source transparency:
   - “Why this step?” with direct excerpts and links to source task.
5. Optimize for field usage:
   - Mobile-friendly layout.
   - Clear, high-contrast procedure cards.

## Stage 8 — Evaluation and Quality Gates
1. Build gold scenario set from representative maintenance and troubleshooting cases.
2. Validate:
   - Retrieval precision and recall.
   - Procedural fidelity to source steps.
   - Citation correctness.
   - Safety instruction compliance.
3. Add regression tests for parser, indexer, and retrieval behavior.
4. Add stress/adversarial tests:
   - Ambiguous symptoms.
   - Partial user input.
   - Cross-system overlap cases.
5. Define release thresholds and block promotion if unmet.

## Stage 9 — Security, Ops, and Deployment
1. Harden container runtime and dependencies.
2. Add operational logging for:
   - User query.
   - Retrieved sources.
   - Final response and confidence.
3. Add observability:
   - Latency, model throughput, retrieval quality signals, failure metrics.
4. Define deployment architecture:
   - Single-node local deployment for workshop/garage environments.
   - Optional scale-out topology later.
5. Define backup and recovery for indexes, configs, and content snapshots.

## Stage 10 — Rollout and Expansion
1. Pilot with a limited technician group.
2. Collect feedback on:
   - Missing steps.
   - Retrieval misses.
   - UX friction.
3. Tune retrieval/prompt policies based on pilot evidence.
4. Expand manual coverage incrementally.
5. Establish long-term content update and model maintenance cadence.

## MVP Boundary (Recommended)
- Manuals: TM-9-2320-280-20-1/2/3 + TM-9-2320-280-10.
- Capabilities: symptom intake, cited troubleshooting guidance, procedural step guidance, contextual Q&A.
- Deployment: local Dockerized open-source LLM + local vector store.
- Deferred capabilities: image reasoning, voice interface, predictive analytics.

