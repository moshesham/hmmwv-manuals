# Stage 1 - Scope, Safety, and Acceptance Criteria

## MVP Scope
### In scope manuals
- `tm-9-2320-280-10`
- `TM-9-2320-280-20-1`
- `TM-9-2320-280-20-2`
- `TM-9-2320-280-20-3`

### In scope user journeys
1. Symptom-to-diagnostic guidance.
2. Step-by-step cited procedure guidance.
3. Follow-up troubleshooting questions within the current diagnostic context.

### Explicitly out of scope for this phase
- Image reasoning.
- Voice interaction.
- Predictive maintenance.
- Uncited free-form repair advice.
- Coverage expansion beyond the MVP manuals.

## Operating Modes
### Hybrid mode model
- Default behavior is inferred-first.
- The detected mode must always be shown prominently to the user.
- The user must be able to override mode selection directly to `operator` or `maintenance`.
- The system must support a third state: `mixed_or_uncertain`.
- In `mixed_or_uncertain`, the system must ask a clarification question before giving procedural advice.

### Mode states
- `operator`: prioritize operator-level guidance and escalation boundaries.
- `maintenance`: prioritize unit-maintenance diagnostics and task procedures.
- `mixed_or_uncertain`: detected evidence spans roles or confidence is too low for safe routing.

### Session confidence behavior
- Maintain a session mode confidence score.
- Allow automatic persistence of inferred mode only after confidence exceeds a defined threshold.
- Reset or lower confidence when a new question introduces conflicting role signals.
- Treat explicit user override as authoritative until the session context materially changes.

## Safety Requirements
1. Always surface relevant warnings, cautions, and notes before the associated procedure or decision step.
2. Never produce procedural guidance without at least one citation to manual, file, and anchor-level provenance.
3. When the source material is ambiguous, conflicting, or absent, respond with insufficient-evidence behavior instead of improvisation.
4. Preserve maintenance ordering when presenting step sequences.
5. Preserve escalation boundaries when the manual directs the user to supervisor, unit maintenance, or another referenced manual.
6. Keep user-visible answers grounded to the selected or detected mode and do not silently mix operator and maintenance guidance.
7. Require clarification before procedural advice whenever mode remains mixed or uncertain.

## Acceptance Criteria
### Retrieval and grounding
- The system can limit retrieval to MVP manuals only.
- Every returned answer includes source manual, source path, and source anchor or equivalent chunk identifier.
- Retrieved evidence must map back to exact source excerpts.

### Mode behavior
- Every response declares the active mode and whether it was inferred, inherited, explicitly selected, or system-defaulted.
- Users can override inferred mode in one action.
- The system can hold a `mixed_or_uncertain` state without forcing unsafe assumptions.
- Automatic mode persistence occurs only when session confidence exceeds the configured threshold.

### Diagnostic behavior
- Symptom queries return a ranked diagnostic path or an explicit insufficient-evidence response.
- Follow-up questions preserve current manual context and do not silently jump to unrelated subsystems.
- Troubleshooting sequences retain yes/no or ordered decision semantics where the source expresses them.

### Procedure behavior
- Procedure answers maintain source step order.
- `INITIAL SETUP` requirements and `FOLLOW-ON TASKS` remain attached to the same task response.
- Safety blocks attached to a task are shown with that task.
- Procedural answers are blocked pending clarification when mode is `mixed_or_uncertain`.

### Offline and operational constraints
- Design assumptions must support fully local execution in later stages.
- No stage 1 artifact should assume a hosted embedding or hosted LLM dependency.

## Review Gates
### Gate 1 - scope fit
- The query can be classified as operator, maintenance, or mixed/uncertain.
- Unsupported requests are rejected or narrowed without hallucinated guidance.

### Gate 2 - mode fit
- The system shows detected mode and confidence to the orchestration layer.
- Explicit overrides take precedence over inference.
- Low-confidence mode selection cannot silently persist into procedural guidance.

### Gate 3 - safety fit
- Answers fail closed when citation or safety attachment is missing.
- High-risk procedural responses cannot bypass associated warnings.
- Mixed/uncertain mode forces clarification before procedural instruction.

### Gate 4 - evidence fit
- Evidence can be inspected by a reviewer without external systems.
- A reviewer can trace an answer back to a file and excerpt.

## Challenged Assumptions
- Assumption: one generic query flow is enough.
  - Challenge: operator and maintenance journeys have different evidence and escalation expectations.
- Assumption: the user should always pick a mode up front.
  - Challenge: explicit-only mode adds friction and slows field use.
- Assumption: the system should always infer and proceed.
  - Challenge: inference-only mode risks unsafe cross-role answers.

## Decisions Made
1. Use four manuals only for the MVP boundary.
2. Use a hybrid mode model with inference first, visible confirmation, and direct override.
3. Treat `mixed_or_uncertain` as a valid operating state that blocks procedural advice pending clarification.
4. Allow inferred mode persistence only after session confidence exceeds a threshold.
5. Require source traceability at the content-unit level before later retrieval work begins.

## Residual Questions
1. What initial threshold should later orchestration stages use for automatic mode persistence?
2. Should the first procedural answer always include a mode-confirmation affordance even at high confidence?
3. How should later stages summarize conflicting evidence when a session shifts from operator to maintenance intent?
